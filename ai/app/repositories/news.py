"""news 읽기·쓰기. 같은 기사는 한 행으로 모으고, 한 번 확보한 본문은 덮어쓰지 않는다.

backend `repositories/news.py` 는 URL 이 같으면 건너뛰기만 했다. 여기서는 같은 기사가 다시
들어오면 **비어 있던 것만 채운다.**

    본문         실패였고 이번에 성공했으면 채운다. 이미 성공한 본문은 그대로 둔다 — 이번에
                 받은 본문이 성공이든 실패든. 실패가 반복되면 마지막 시도의 사유·시각만 남긴다.
                 보관 정책으로 지운 본문(purged)은 다시 받아도 되살리지 않는다
    발행 시각    비어 있으면 채운다 (텔레그램 링크로 먼저 들어온 기사를 네이버가 다시 찾은 경우)
    제목·요약    비어 있으면 채운다
    주소·경로    처음 것을 둔다. 다른 경로로 발견한 기록은 telegram_message_links 에 남는다

같은 기사인지는 canonical_url(services/news/url.py)로 가른다. 이관 전 행은 canonical_url 이
비어 있을 수 있어서 원래 주소로도 찾는다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import News, TelegramMessageLink
from app.services.news.url import canonical_url

# 본문 칼럼. 성공한 본문을 채울 때 함께 바뀐다.
BODY_FIELDS = ("cleaned_text", "body_status", "body_error", "body_fetched_at", "body_extractor")
# 실패가 반복됐을 때 바꾸는 칼럼. 본문(cleaned_text)과 상태는 실패 그대로다.
RETRY_FIELDS = ("body_error", "body_fetched_at", "body_extractor")


@dataclass
class NewsSaveResult:
    """save_news 의 결과. ids 는 넘긴 행 순서대로 각 행이 들어간 news.id 다."""

    ids: list[int] = field(default_factory=list)
    inserted: int = 0  # 새 기사
    filled: int = 0  # 실패했던 본문을 이번에 채운 기사
    existing: int = 0  # 이미 있던 기사 (본문 보완 포함)


async def lock_news_keys(session: AsyncSession, keys: list[str]) -> None:
    """같은 기사를 동시에 저장하는 다른 수집기와 차례를 맞춘다.

    조회와 INSERT 사이에 다른 수집기가 같은 기사를 넣으면 고유키 오류로 그 실행 전체가
    롤백된다. 트랜잭션이 끝날 때 풀리는 잠금을 정렬한 순서로 잡아 교착을 피한다.
    """
    for key in sorted(set(keys)):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"news:{key}"}
        )


async def _find(session: AsyncSession, key: str, url: str) -> News | None:
    found = await session.execute(
        select(News).where(or_(News.canonical_url == key, News.url == url))
        # 정규화 주소로 찾은 행을 먼저 쓴다. 원래 주소만 같은 행은 이관 전 행이다.
        .order_by((News.canonical_url == key).desc().nulls_last(), News.id)
        .limit(1)
        # purge는 advisory lock을 쓰지 않는다. 진행 중인 삭제를 기다리고 최신 상태를 읽는다.
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return found.scalar_one_or_none()


def _merge(news: News, row: dict, key: str) -> bool:
    """이미 있는 기사에 이번 행을 합친다. 실패했던 본문을 채웠으면 True.

    보관 정책으로 본문을 지운 기사(purged)는 다시 받은 내용으로 채우지 않는다. 출처 정보인
    발행 시각과 정규화 주소만 채운다 — 제목·요약도 원문의 일부라 되살리지 않는다.
    """
    if news.body_status == "purged":
        if news.published_at is None and row.get("published_at") is not None:
            news.published_at = row["published_at"]
        if news.canonical_url is None:
            news.canonical_url = key
        return False
    filled = False
    if news.body_status != "ok":
        if row["body_status"] == "ok":
            for name in BODY_FIELDS:
                setattr(news, name, row[name])
            filled = True
        elif row.get("body_fetched_at") is not None:
            for name in RETRY_FIELDS:
                setattr(news, name, row[name])
    if news.published_at is None and row.get("published_at") is not None:
        news.published_at = row["published_at"]
    if not news.title and row.get("title"):
        news.title = row["title"]
    if not news.summary and row.get("summary"):
        news.summary = row["summary"]
    # _find 가 정규화 주소로 못 찾았으니 이 주소를 가진 다른 행은 없다(잠금 안에서).
    if news.canonical_url is None:
        news.canonical_url = key
    return filled


async def save_news(session: AsyncSession, rows: list[dict]) -> NewsSaveResult:
    """기사 행을 넣거나 합친다. 커밋은 부르는 쪽이 한다.

    행의 키는 News 칼럼 이름이다(canonical_url 은 url 에서 여기서 만든다). body_status 가
    ok 면 cleaned_text 에 비어 있지 않은 정제 본문이 있어야 한다. 링크 경로는 전문,
    네이버 검색 경로는 clean_text의 길이 제한(3000자)을 적용한다. 3문장 발췌는 별도다.
    """
    result = NewsSaveResult()
    keys = [canonical_url(row["url"]) for row in rows]
    await lock_news_keys(session, keys)
    for row, key in zip(rows, keys, strict=True):
        if row["body_status"] == "ok" and not row.get("cleaned_text"):
            raise ValueError(f"본문 없이 ok 로 저장할 수 없다: {row['url']}")
        news = await _find(session, key, row["url"])
        if news is None:
            news = News(**{**row, "canonical_url": key})
            session.add(news)
            await session.flush()  # 같은 묶음에 같은 기사가 또 있으면 다음 _find 가 찾는다
            result.inserted += 1
        else:
            result.filled += _merge(news, row, key)
            result.existing += 1
            await session.flush()
        result.ids.append(news.id)
    return result


async def known_news_keys(session: AsyncSession, urls: list[str]) -> set[str]:
    """이미 news 에 있는 기사의 정규화 주소. 수집량 상한을 셀 때 새 기사만 세려고 쓴다."""
    keys = {canonical_url(url) for url in urls}
    if not keys:
        return set()
    rows = await session.execute(
        select(News.canonical_url, News.url).where(
            or_(News.canonical_url.in_(keys), News.url.in_(urls))
        )
    )
    return {stored or canonical_url(url) for stored, url in rows.all()} & keys


@dataclass(frozen=True)
class KnownArticle:
    id: int
    url: str
    canonical_url: str
    status: str
    fetched_at: datetime | None


async def known_articles(session: AsyncSession, urls: list[str]) -> dict[str, KnownArticle]:
    """원문 주소 또는 과거 발견 주소로 기존 기사를 찾는다. 본문은 읽지 않는다."""
    if not urls:
        return {}
    columns = (News.id, News.url, News.canonical_url, News.body_status, News.body_fetched_at)
    result: dict[str, KnownArticle] = {}
    rows = await session.execute(
        select(TelegramMessageLink.discovered_url, *columns)
        .join(News, News.id == TelegramMessageLink.news_id)
        .where(TelegramMessageLink.discovered_url.in_(urls)).order_by(News.id)
    )
    for discovered, news_id, url, key, status, fetched in rows:
        result.setdefault(discovered, KnownArticle(news_id, url, key or canonical_url(url),
                                                  status, fetched))
    keys = {canonical_url(url) for url in urls}
    rows = await session.execute(select(*columns).where(
        or_(News.canonical_url.in_(keys), News.url.in_(urls))))
    by_key = {key or canonical_url(url): KnownArticle(
        news_id, url, key or canonical_url(url), status, fetched
    ) for news_id, url, key, status, fetched in rows}
    for url in urls:
        if canonical_url(url) in by_key:
            result.setdefault(url, by_key[canonical_url(url)])
    return result


async def failed_news(
    session: AsyncSession, *, source: str, since: datetime, limit: int
) -> list[News]:
    """본문을 못 얻은 기사 중 발행(모르면 수집)이 since 이후인 것. 재시도 대상이다."""
    rows = await session.execute(
        select(News)
        .where(
            News.source == source,
            News.body_status == "failed",
            func.coalesce(News.published_at, News.collected_at) >= since,
        )
        .order_by(News.id)
        .limit(limit)
    )
    return list(rows.scalars().all())
