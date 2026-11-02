"""공통 ID 를 고르고(stock_card_ids), 그 ID 로 원문을 읽는다(get_sources).

**본문은 요청할 때만 준다(include_body).** 원문은 팀 내부의 분류·검증에만 쓴다.
출처·시각·본문 유무와 없는 사유는 늘 주고, 본문이 필요한
코드는 include_body=True 를 적는다. 그래야 원문을 읽는 곳을 코드에서 찾을 수 있다.

**기준 시각(cutoff)을 주면 그 뒤에 받은 본문은 주지 않는다.** stock_card_ids 는 자료가 기준
시각 전에 공개됐는지를 보지만, 본문은 나중에 받았을 수 있다. 10시 기사를 18시에 받았다면
14시 기준 보고서에 그 본문을 쓸 수 없다 — 14시 당시와 같았다는 보장이 없다.
요약은 cutoff 를 주면 늘 뺀다. 나중에 채우거나 덮어쓰는데 그 시각을 남기지 않는다.
"""

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.scope import KST
from app.models import (
    AnalystReport,
    Channel,
    DartDisclosure,
    News,
    SourceCard,
    SourceCardStock,
    TelegramMessage,
    TelegramMessageLink,
)
from app.repositories.source_card.read_model import (
    Discovery,
    SourceRecord,
    disclosure_record,
    discovery,
    hide_after_cutoff,
    message_record,
    news_record,
    pdf_record,
)


def available_since(since: datetime):
    """카드가 since 이후에 공개됐다는 조건. 공개 시각을 모르는 자료는 날짜(KST)로 판단한다."""
    return or_(SourceCard.available_at >= since, and_(
        SourceCard.available_at.is_(None),
        SourceCard.event_date >= since.astimezone(KST).date(),
    ))


def available_within(until: datetime, since: datetime | None = None):
    """카드가 기준 시각(until) 이전에, since 이후에 공개됐다는 조건. 종목 조회 두 곳이 같이 쓴다
    (이 함수의 stock_card_ids 와 repositories/classification.py 의 classified_sources).

    공개 시각을 모르는 자료(시각 없이 작성일만 있는 네이버 리포트)는 날짜로 판단한다.
    기준 시각의 날짜(KST)보다 **앞선 날** 것만 넣는다 — 같은 날이면 기준 시각 전인지 알 수 없다.
    공개 시각도 날짜도 모르는 자료는 넣지 않는다.
    """
    condition = or_(SourceCard.available_at <= until, and_(
        SourceCard.available_at.is_(None),
        SourceCard.event_date < until.astimezone(KST).date(),
    ))
    return condition if since is None else and_(condition, available_since(since))


async def stock_card_ids(
    session: AsyncSession, stock_code: str, *, until: datetime, since: datetime | None = None,
) -> list[int]:
    """종목 하나의 자료 중 기준 시각(until) 이전에 공개된 것의 공통 ID. 오래된 순서다.

    시각 조건은 available_within 이다. 이 색인(source_card_stocks)에는 종목에 직접 해당하는 자료만
    있다 — 분류 판정의 INDIRECT_CONTEXT·공통 배경까지 보려면 classification.classified_sources.
    """
    # (카드, 종목)이 고유하므로 종목 하나로 조인하면 카드가 겹치지 않는다.
    query = (
        select(SourceCard.id)
        .join(SourceCardStock, SourceCardStock.source_card_id == SourceCard.id)
        .where(SourceCardStock.stock_code == stock_code, available_within(until, since))
        .order_by(SourceCard.event_date, SourceCard.available_at.nulls_first(), SourceCard.id)
    )
    return list((await session.execute(query)).scalars().all())


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


async def get_sources(
    session: AsyncSession, card_ids: list[int], *, include_body: bool = False,
    cutoff: datetime | None = None,
) -> list[SourceRecord]:
    """공통 ID 들로 원문을 읽는다. 결과는 넘긴 순서대로이고, 없는 ID 는 빠진다.

    본문은 include_body=True 일 때만 담는다(맨 위 설명). 본문이 없으면 그 사유를
    body_missing_reason 에 늘 담는다. 기사·PDF 는 그것을 공유한 텔레그램 메시지들을, 메시지는
    그 메시지가 건 링크·첨부를 discoveries 에 담는다.

    cutoff 는 보고서 기준 시각이다. 주면 그 뒤에 받은 본문은 없는 것으로 보고 사유를
    not_observed_at_cutoff 로 적고, 요약은 늘 뺀다(규칙은 hide_after_cutoff). stock_card_ids 에
    준 until 과 같은 값을 넘긴다. cutoff 는 시간대가 있어야 한다.
    """
    if cutoff is not None and cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
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
    disclosure_ids = [
        c.dart_disclosure_id for c in cards.values() if c.dart_disclosure_id is not None
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
    disclosures = {d.id: d for d in (
        await session.execute(select(DartDisclosure).where(DartDisclosure.id.in_(disclosure_ids)))
    ).scalars()}

    found: dict[tuple[str, int], list[Discovery]] = {}
    for row in await _discoveries(session, TelegramMessageLink.news_id.in_(news_ids)
                                  | TelegramMessageLink.analyst_report_id.in_(report_ids)
                                  | TelegramMessageLink.message_id.in_(message_ids)):
        link, message = row[0], row[1]
        item = discovery(*row)
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
            record = news_record(card, *news[card.news_id], include_body)
        elif card.analyst_report_id in reports:
            record = pdf_record(card, *reports[card.analyst_report_id], include_body)
        elif card.telegram_message_id in messages:
            record = message_record(card, *messages[card.telegram_message_id], include_body)
        elif card.dart_disclosure_id in disclosures:
            record = disclosure_record(card, disclosures[card.dart_disclosure_id])
        else:
            continue  # 원문 표를 가리키지 않는 카드(backend 의 다른 종류)
        if cutoff is not None:
            hide_after_cutoff(record, cutoff)
        record.discoveries = found.get((record.kind, record.raw_id), [])
        records.append(record)
    return records
