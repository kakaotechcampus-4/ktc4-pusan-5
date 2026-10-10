"""공통 자료 ID(source_card) 등록과 조회.

    register_missing_sources   카드가 없는 원문(news·analyst_reports·telegram_messages)에 카드를
                               만든다. 몇 번을 돌려도 결과가 같다 — 원문 하나에 카드 하나라는
                               고유 제약이 있고, 이미 카드가 있는 원문은 고르지 않는다
    backfill_canonical_urls    이관 전 news 행의 canonical_url 을 채운다
    get_sources                공통 ID 로 원문·메타데이터·발견 경로를 읽는다

카드에는 원문을 복제하지 않는다. 원 발행처(source_name)와 채널만 적고 본문은 FK 로 읽는다.

**본문은 요청할 때만 준다(include_body).** 원문은 팀 내부의 분류·검증에만 쓴다.
출처·시각·본문 유무와 없는 사유는 늘 주고, 본문이 필요한
코드는 include_body=True 를 적는다. 그래야 원문을 읽는 곳을 코드에서 찾을 수 있다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import and_, exists, func, literal, null, select, tuple_
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models import (
    AnalystReport,
    Channel,
    News,
    SourceCard,
    TelegramMessage,
    TelegramMessageLink,
)
from app.repositories.news import lock_news_keys
from app.services.news.url import canonical_url

CARD_COLUMNS = ["card_type", "source_name", "channel_id", "collected_at", "tags", "payload",
                "created_at"]

# 원문 표의 경로 값을 사람이 읽는 수집 경로로. 자료 형태(card_type)·원 발행처(source_name)와
# 다른 정보다. 증권사 PDF 를 텔레그램에서 받았다면 pdf · 증권사 · telegram_attachment 다.
COLLECTION_PATHS = {
    ("news", "naver"): "naver_news_search",
    ("news", "telegram"): "telegram_link",
    ("pdf", "naver"): "naver_research",
    ("pdf", "telegram"): "telegram_attachment",
    ("message", "web"): "telegram_web",
    ("message", "telethon"): "telegram_client",
}


def _card_values(card_type: str, source_name, channel_id, collected_at) -> list:
    """INSERT ... SELECT 의 공통 칼럼. backend 가 DB 기본값 없이 만든 칼럼(tags·payload·
    created_at)도 값을 준다."""
    return [
        literal(card_type),
        func.left(source_name, 100),
        null() if channel_id is None else channel_id,
        collected_at,
        literal([], JSONB),
        literal({}, JSONB),
        func.now(),
    ]


async def _register(session: AsyncSession, fk_name: str, query) -> int:
    stmt = (
        insert(SourceCard)
        .from_select([*CARD_COLUMNS, fk_name], query)
        .on_conflict_do_nothing()
        .returning(SourceCard.id)
    )
    return len((await session.execute(stmt)).scalars().all())


async def register_missing_sources(
    session: AsyncSession, *, news_ids: list[int] | None = None,
    report_ids: list[int] | None = None, message_ids: list[int] | None = None,
    report_keys: list[tuple[str, str, str]] | None = None,
) -> dict[str, int]:
    """카드가 없는 원문을 등록한다. None은 전체 복구, 빈 목록은 해당 종류 제외.

    일반 수집은 이번 묶음의 ID만 전달한다. 커밋은 부르는 쪽이 한다.
    """
    # 원문 id 순서로 만든다. 카드 번호가 원문이 들어온 순서를 따라가 읽기 쉽다.
    news = select(
        *_card_values("news", News.publisher, None, News.collected_at), News.id
    ).where(~exists().where(SourceCard.news_id == News.id)).order_by(News.id)

    # 텔레그램 첨부 PDF 는 채널을 잇는다. channel 에 그 채널 행이 있을 때만 이어진다.
    pdf = (
        select(
            *_card_values("pdf", AnalystReport.broker, Channel.id, AnalystReport.collected_at),
            AnalystReport.id,
        )
        .select_from(AnalystReport)
        .outerjoin(Channel, and_(
            AnalystReport.source == "telegram",
            Channel.telegram_handle == AnalystReport.source_category,
        ))
        .where(~exists().where(SourceCard.analyst_report_id == AnalystReport.id))
        .order_by(AnalystReport.id)
    )

    # 다른 채널 글을 전달한 메시지의 원 발행처는 원래 채널이다. 운영자가 쓴 글이면 이 채널이다.
    message = (
        select(
            *_card_values("message", func.coalesce(TelegramMessage.forwarded_from, Channel.name),
                          TelegramMessage.channel_id, TelegramMessage.collected_at),
            TelegramMessage.id,
        )
        .join(Channel, Channel.id == TelegramMessage.channel_id)
        .where(~exists().where(SourceCard.telegram_message_id == TelegramMessage.id))
        .order_by(TelegramMessage.id)
    )
    if report_keys is not None:
        pdf = pdf.where(tuple_(
            AnalystReport.source, AnalystReport.source_category, AnalystReport.source_id,
        ).in_(report_keys))
    counts = {}
    for kind, fk, query, column, ids in (
        ("news", "news_id", news, News.id, news_ids),
        ("pdf", "analyst_report_id", pdf, AnalystReport.id, report_ids),
        ("message", "telegram_message_id", message, TelegramMessage.id, message_ids),
    ):
        counts[kind] = 0 if ids == [] else await _register(
            session, fk, query if ids is None else query.where(column.in_(ids)),
        )
    return counts


@dataclass
class CanonicalBackfill:
    filled: int = 0
    # (news.id, 정규화 주소) — 이미 다른 행이 그 주소를 가져 비워 둔 행. 같은 기사가 이관 전에
    # 두 행으로 들어간 것이다. 합치지 않는다(카드·인용이 붙어 있을 수 있다). 사람이 확인한다.
    collisions: list[tuple[int, str]] = field(default_factory=list)


async def backfill_canonical_urls(session: AsyncSession) -> CanonicalBackfill:
    """canonical_url 이 빈 news 행을 채운다. 여러 번 돌려도 된다. 커밋은 부르는 쪽이 한다."""
    result = CanonicalBackfill()
    rows = (
        await session.execute(
            select(News.id, News.url).where(News.canonical_url.is_(None)).order_by(News.id)
        )
    ).all()
    keyed = [(news_id, canonical_url(url)) for news_id, url in rows]
    # 행 ID 순서와 URL 순서는 다를 수 있다. 수집기와 같은 순서로 잠금을 모두 잡는다.
    await lock_news_keys(session, [key for _, key in keyed])
    for news_id, key in keyed:
        taken = (
            await session.execute(select(News.id).where(News.canonical_url == key))
        ).scalar_one_or_none()
        if taken == news_id:
            continue  # 잠금을 기다리는 사이 다른 등록 실행이 이 행을 채웠다.
        if taken is not None:
            result.collisions.append((news_id, key))
            continue
        news = await session.get(News, news_id)
        news.canonical_url = key
        await session.flush()
        result.filled += 1
    return result


@dataclass
class Discovery:
    """텔레그램 메시지에서 자료를 발견한 기록 하나. 메시지 쪽에서 보면 그 메시지가 건 링크다."""

    message_card_id: int | None  # 메시지의 공통 ID (등록 전이면 None)
    channel: str
    message_url: str
    posted_at: datetime | None
    kind: str  # url | attachment
    discovered_url: str | None  # 메시지에 적힌 주소 그대로
    final_url: str | None  # 따라가 도착한 주소
    status: str
    target_card_id: int | None  # 이어진 기사·PDF 의 공통 ID


@dataclass
class SourceRecord:
    """공통 ID 하나로 읽은 원문. 형태·발행처·수집 경로를 따로 둔다."""

    id: int  # 공통 자료 ID (source_card.id)
    kind: str  # 자료 형태: news | pdf | message
    raw_id: int  # 원문 표의 id
    title: str | None
    url: str | None  # 원문 주소
    # 원 발행처: 기사는 도메인, PDF 는 증권사, 메시지는 채널 이름(전달된 글이면 원래 채널)
    publisher: str | None
    collection_path: str  # 수집 경로 (COLLECTION_PATHS)
    channel: str | None  # 텔레그램에서 온 자료의 채널
    published_at: datetime | None  # 기사 발행 시각·메시지 게시 시각. 모르면 None
    write_date: date | None  # PDF 작성일 (시각이 없다)
    collected_at: datetime | None
    has_body: bool  # 본문이 있는가 (include_body 와 상관없이 알려준다)
    # 본문이 없으면 그 사유. 있으면 None.
    #   failed: <사유>   열었지만 본문을 못 얻었다 (기사)
    #   empty·unusable·pending·skipped·failed  PDF 본문 상태 그대로 (analyst_reports)
    #   empty            글자 없이 첨부만 올린 메시지
    #   purged: ...      보관 정책으로 지웠다. 재분류·과거 결과 검증에 쓸 수 없다
    body_missing_reason: str | None
    body_status: str | None  # 원문 표의 상태 값 그대로 (기사 ok|failed|purged, PDF ok|empty|...)
    body_error: str | None
    body_fetched_at: datetime | None  # 본문을 받은 시각
    summary: str | None  # 네이버가 준 요약. 본문 아님
    body: str | None = None  # 저장된 정제 본문. 네이버 기사는 최대 3000자. include_body=True만
    edited: bool | None = None  # 메시지만: 수정 표시가 있었다
    edit_detected_at: datetime | None = None  # 메시지만: 다시 수집했을 때 본문이 달랐던 첫 시각
    forwarded_from_url: str | None = None  # 메시지만: 전달된 글이면 원글 주소
    discoveries: list[Discovery] = field(default_factory=list)


def _purged(purged_at: datetime | None, reason: str | None) -> str:
    when = f"{purged_at:%Y-%m-%d}" if purged_at else "시각 미상"
    return f"purged: 보관 정책으로 삭제 ({when}) {reason or ''}".rstrip()


def _news_record(card: SourceCard, news: News, has_body: bool, include_body: bool) -> SourceRecord:
    missing = None if has_body else (
        _purged(news.purged_at, news.purge_reason) if news.body_status == "purged"
        else f"failed: {news.body_error or '사유 미기록'}")
    return SourceRecord(
        id=card.id, kind="news", raw_id=news.id, title=news.title or None, url=news.url,
        publisher=news.publisher,
        collection_path=COLLECTION_PATHS.get(("news", news.source), news.source),
        channel=None, published_at=news.published_at, write_date=None,
        collected_at=news.collected_at, has_body=has_body, body_missing_reason=missing,
        body_status=news.body_status, body_error=news.body_error,
        body_fetched_at=news.body_fetched_at, summary=news.summary or None,
        body=news.cleaned_text if include_body else None,
    )


def _pdf_record(
    card: SourceCard, report: AnalystReport, has_body: bool, include_body: bool,
) -> SourceRecord:
    telegram = report.source == "telegram"
    missing = None if has_body else (
        _purged(report.purged_at, report.purge_reason) if report.body_status == "purged"
        else report.body_status + (f": {report.body_error}" if report.body_error else ""))
    return SourceRecord(
        id=card.id, kind="pdf", raw_id=report.id, title=report.title,
        url=report.end_url or report.attach_url, publisher=report.broker,
        collection_path=COLLECTION_PATHS.get(("pdf", report.source), report.source),
        channel=report.source_category if telegram else None, published_at=None,
        write_date=report.write_date, collected_at=report.collected_at, has_body=has_body,
        body_missing_reason=missing, body_status=report.body_status,
        body_error=report.body_error, body_fetched_at=report.body_fetched_at,
        summary=report.summary_text, body=report.body_text if include_body else None,
    )


def _message_record(
    card: SourceCard, message: TelegramMessage, channel: Channel, has_body: bool, include_body: bool
) -> SourceRecord:
    if message.purged_at is not None:
        status, missing = "purged", _purged(message.purged_at, message.purge_reason)
    else:
        status = "ok" if has_body else "empty"
        missing = None if has_body else "empty: 글자 없이 첨부만 올린 메시지"
    return SourceRecord(
        id=card.id, kind="message", raw_id=message.id, title=None, url=message.url,
        publisher=message.forwarded_from or channel.name,
        collection_path=COLLECTION_PATHS.get(("message", message.collected_via),
                                             message.collected_via),
        channel=channel.telegram_handle, published_at=message.posted_at, write_date=None,
        collected_at=message.collected_at, has_body=has_body, body_missing_reason=missing,
        body_status=status, body_error=None, body_fetched_at=message.collected_at, summary=None,
        body=message.text if include_body else None, edited=message.edited,
        edit_detected_at=message.edit_detected_at,
        forwarded_from_url=message.forwarded_from_url,
    )


async def _discoveries(session: AsyncSession, condition) -> list[tuple]:
    """(링크 행, 메시지, 채널, 메시지 카드 id, 대상 카드 id) 를 메시지 게시 순으로."""
    message_card = select(SourceCard.id).where(
        SourceCard.telegram_message_id == TelegramMessage.id
    ).scalar_subquery()
    target_card = select(SourceCard.id).where(
        (SourceCard.news_id == TelegramMessageLink.news_id)
        | (SourceCard.analyst_report_id == TelegramMessageLink.analyst_report_id)
    ).limit(1).scalar_subquery()
    rows = await session.execute(
        select(TelegramMessageLink, TelegramMessage, Channel, message_card, target_card)
        .options(defer(TelegramMessage.text, raiseload=True))
        .join(TelegramMessage, TelegramMessage.id == TelegramMessageLink.message_id)
        .join(Channel, Channel.id == TelegramMessage.channel_id)
        .where(condition)
        .order_by(TelegramMessage.posted_at.nulls_last(), TelegramMessage.id,
                  TelegramMessageLink.kind, TelegramMessageLink.position)
    )
    return list(rows.all())


def _discovery(link, message, channel, message_card_id, target_card_id) -> Discovery:
    return Discovery(
        message_card_id=message_card_id, channel=channel.telegram_handle, message_url=message.url,
        posted_at=message.posted_at, kind=link.kind, discovered_url=link.discovered_url,
        final_url=link.final_url, status=link.status, target_card_id=target_card_id,
    )


async def get_sources(
    session: AsyncSession, card_ids: list[int], *, include_body: bool = False
) -> list[SourceRecord]:
    """공통 ID 들로 원문을 읽는다. 결과는 넘긴 순서대로이고, 없는 ID 는 빠진다.

    본문은 include_body=True 일 때만 담는다(맨 위 설명). 본문이 없으면 그 사유를
    body_missing_reason 에 늘 담는다. 기사·PDF 는 그것을 공유한 텔레그램 메시지들을, 메시지는
    그 메시지가 건 링크·첨부를 discoveries 에 담는다.
    """
    cards = {
        card.id: card
        for card in (
            await session.execute(select(SourceCard).where(SourceCard.id.in_(card_ids)).options(
                defer(SourceCard.raw_text, raiseload=True),
                defer(SourceCard.cleaned_text, raiseload=True),
            ))
        ).scalars()
    }
    news_ids = [c.news_id for c in cards.values() if c.news_id is not None]
    report_ids = [c.analyst_report_id for c in cards.values() if c.analyst_report_id is not None]
    message_ids = [
        c.telegram_message_id for c in cards.values() if c.telegram_message_id is not None
    ]

    # 유무만 DB에서 계산한다. 본문 미요청 시 큰 문자열을 Python으로 전송하지 않는다.
    news_query = select(News, func.coalesce(News.cleaned_text != "", False))
    report_query = select(AnalystReport, func.coalesce(AnalystReport.body_text != "", False))
    message_query = select(
        TelegramMessage, Channel, func.coalesce(TelegramMessage.text != "", False),
    )
    if not include_body:
        news_query = news_query.options(defer(News.cleaned_text, raiseload=True))
        report_query = report_query.options(defer(AnalystReport.body_text, raiseload=True))
        message_query = message_query.options(defer(TelegramMessage.text, raiseload=True))
    news = {n.id: (n, present) for n, present in (
        await session.execute(news_query.where(News.id.in_(news_ids)))
    ).all()}
    reports = {r.id: (r, present) for r, present in (
        await session.execute(report_query.where(AnalystReport.id.in_(report_ids)))
    ).all()}
    messages = {m.id: (m, ch, present) for m, ch, present in (
        await session.execute(
            message_query
            .join(Channel, Channel.id == TelegramMessage.channel_id)
            .where(TelegramMessage.id.in_(message_ids))
        )
    ).all()}

    found: dict[tuple[str, int], list[Discovery]] = {}
    for row in await _discoveries(session, TelegramMessageLink.news_id.in_(news_ids)
                                  | TelegramMessageLink.analyst_report_id.in_(report_ids)
                                  | TelegramMessageLink.message_id.in_(message_ids)):
        link, message = row[0], row[1]
        item = _discovery(*row)
        if link.news_id in news:
            found.setdefault(("news", link.news_id), []).append(item)
        if link.analyst_report_id in reports:
            found.setdefault(("pdf", link.analyst_report_id), []).append(item)
        if message.id in messages:
            found.setdefault(("message", message.id), []).append(item)

    records: list[SourceRecord] = []
    for card_id in card_ids:
        card = cards.get(card_id)
        if card is None:
            continue
        if card.news_id in news:
            record = _news_record(card, *news[card.news_id], include_body)
        elif card.analyst_report_id in reports:
            record = _pdf_record(card, *reports[card.analyst_report_id], include_body)
        elif card.telegram_message_id in messages:
            record = _message_record(card, *messages[card.telegram_message_id], include_body)
        else:
            continue  # 원문 표를 가리키지 않는 카드(backend 의 다른 종류)
        record.discoveries = found.get((record.kind, record.raw_id), [])
        records.append(record)
    return records
