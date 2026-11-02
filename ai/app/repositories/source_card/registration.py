"""카드를 만들고 공개 시각·날짜·종목을 적는다. 커밋은 부르는 쪽이 한다.
"""

from dataclasses import dataclass, field

from sqlalchemy import (
    Date,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    tuple_,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.repositories.news import lock_news_keys
from app.services.news.url import canonical_url

CARD_COLUMNS = ["card_type", "source_name", "channel_id", "collected_at", "tags", "payload",
                "created_at"]


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
    disclosure_ids: list[int] | None = None,
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

    # 공시의 원 발행처는 제출인이다. 대개 회사 자신이고, 대량보유 보고 등은 다른 주체다.
    disclosure = select(
        *_card_values("disclosure", DartDisclosure.flr_nm, None, DartDisclosure.first_seen_at),
        DartDisclosure.id,
    ).where(
        ~exists().where(SourceCard.dart_disclosure_id == DartDisclosure.id)
    ).order_by(DartDisclosure.id)
    if report_keys is not None:
        pdf = pdf.where(tuple_(
            AnalystReport.source, AnalystReport.source_category, AnalystReport.source_id,
        ).in_(report_keys))
    counts = {}
    for kind, fk, query, column, ids in (
        ("news", "news_id", news, News.id, news_ids),
        ("pdf", "analyst_report_id", pdf, AnalystReport.id, report_ids),
        ("message", "telegram_message_id", message, TelegramMessage.id, message_ids),
        ("disclosure", "dart_disclosure_id", disclosure, DartDisclosure.id, disclosure_ids),
    ):
        counts[kind] = 0 if ids == [] else await _register(
            session, fk, query if ids is None else query.where(column.in_(ids)),
        )
    targets = _target_cards(news_ids, report_ids, message_ids, report_keys, disclosure_ids)
    if targets is not None:
        await index_cards(session, targets)
    return counts


def _target_cards(news_ids, report_ids, message_ids, report_keys, disclosure_ids):
    """register_missing_sources 가 받은 원문 범위의 카드를 고르는 조건. 고를 것이 없으면 None."""
    conditions = []
    for column, ids in (
        (SourceCard.news_id, news_ids),
        (SourceCard.analyst_report_id, report_ids),
        (SourceCard.telegram_message_id, message_ids),
        (SourceCard.dart_disclosure_id, disclosure_ids),
    ):
        if ids == []:
            continue
        condition = column.is_not(None) if ids is None else column.in_(ids)
        if column is SourceCard.analyst_report_id and report_keys is not None:
            # correlate(None): analyst_reports 를 FROM 에 둔 쿼리 안에서도 따로 도는 하위 쿼리다
            keyed = select(AnalystReport.id).where(tuple_(
                AnalystReport.source, AnalystReport.source_category, AnalystReport.source_id,
            ).in_(report_keys)).correlate(None)
            condition = and_(condition, column.in_(keyed))
        conditions.append(condition)
    return or_(*conditions) if conditions else None


async def index_cards(session: AsyncSession, condition) -> None:
    """고른 카드의 공개 시각(available_at)·날짜(event_date)·종목(source_card_stocks)을 적는다.

    매번 원문에서 다시 계산한다. 같은 기사를 더 이른 메시지가 건 것을 나중에 수집하면
    공개 시각이 앞당겨진다. 종목은 더하기만 한다 — 다른 방식으로 정한 종목을 지우지 않는다.
    """
    # 자료가 공개돼 있었다는 증거가 되는 시각들. 그중 가장 이른 것을 쓴다.
    def posted_via(link_column, card_column):
        """이 자료를 건 텔레그램 메시지들의 게시 시각."""
        return (
            select(SourceCard.id.label("card_id"), TelegramMessage.posted_at.label("seen_at"))
            .join(TelegramMessageLink, link_column == card_column)
            .join(TelegramMessage, TelegramMessage.id == TelegramMessageLink.message_id)
            .where(condition)
        )

    seen = union_all(
        select(SourceCard.id.label("card_id"), News.published_at.label("seen_at"))
        .join(News, News.id == SourceCard.news_id).where(condition),
        posted_via(TelegramMessageLink.news_id, SourceCard.news_id),
        posted_via(TelegramMessageLink.analyst_report_id, SourceCard.analyst_report_id),
        select(SourceCard.id.label("card_id"), TelegramMessage.posted_at.label("seen_at"))
        .join(TelegramMessage, TelegramMessage.id == SourceCard.telegram_message_id)
        .where(condition),
        # 공시는 처음 본 시각을 접수일 안에 봤을 때만 쓴다. 지난 날짜를 나중에 받았으면 그 시각은
        # 실제 공시보다 한참 늦으므로 NULL 로 두고 아래 event_date(접수일)로 판단하게 한다.
        select(SourceCard.id.label("card_id"), case(
            (cast(func.timezone("Asia/Seoul", DartDisclosure.first_seen_at), Date)
             <= DartDisclosure.rcept_dt, DartDisclosure.first_seen_at),
        ).label("seen_at"))
        .join(DartDisclosure, DartDisclosure.id == SourceCard.dart_disclosure_id)
        .where(condition),
    ).subquery()
    earliest = (
        select(seen.c.card_id, func.min(seen.c.seen_at).label("seen_at"))
        .group_by(seen.c.card_id)
        .subquery()
    )
    await session.execute(
        update(SourceCard)
        .where(SourceCard.id == earliest.c.card_id,
               SourceCard.available_at.is_distinct_from(earliest.c.seen_at))
        .values(available_at=earliest.c.seen_at)
    )

    # 날짜는 KST. 시각을 모르는 네이버 리포트는 작성일, 공시는 접수일이다.
    write_date = select(AnalystReport.write_date).where(
        AnalystReport.id == SourceCard.analyst_report_id
    ).scalar_subquery()
    rcept_dt = select(DartDisclosure.rcept_dt).where(
        DartDisclosure.id == SourceCard.dart_disclosure_id
    ).scalar_subquery()
    event_date = func.coalesce(
        cast(func.timezone("Asia/Seoul", SourceCard.available_at), Date), write_date, rcept_dt,
    )
    await session.execute(
        update(SourceCard)
        .where(condition, SourceCard.event_date.is_distinct_from(event_date))
        .values(event_date=event_date)
    )

    # 증권사 종목분석 리포트는 리포트가 준 종목코드로 잇는다.
    await session.execute(
        insert(SourceCardStock)
        .from_select(
            ["source_card_id", "stock_code", "tagged_by"],
            select(SourceCard.id, AnalystReport.item_code, literal("report_item_code"))
            .join(AnalystReport, AnalystReport.id == SourceCard.analyst_report_id)
            .where(condition, AnalystReport.item_code.is_not(None), AnalystReport.item_code != ""),
        )
        .on_conflict_do_nothing()
    )
    await session.execute(
        insert(SourceCardStock)
        .from_select(
            ["source_card_id", "stock_code", "tagged_by"],
            select(SourceCard.id, DartDisclosure.stock_code, literal("dart_stock_code"))
            .join(DartDisclosure, DartDisclosure.id == SourceCard.dart_disclosure_id)
            .where(condition, DartDisclosure.stock_code != ""),
        )
        .on_conflict_do_nothing()
    )


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
