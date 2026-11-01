"""출처 주소 → 공통 ID. 보고서 출처를 원문에 이을 때 쓴다.
"""

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DartDisclosure, News, SourceCard, TelegramMessage
from app.services.news.url import canonical_url


async def card_ids_for_urls(session: AsyncSession, urls: list[str]) -> dict[str, int]:
    """출처 주소 → 공통 ID. DB 에 원문이 없거나 아직 카드가 없는 주소는 빠진다.

    텔레그램 메시지는 저장한 주소(telegram_messages.url)와 글자가 같아야 하고, 기사는 정규화
    주소(news.canonical_url)로 찾는다. 둘 다 맞으면 메시지가 먼저다. 공시는 DART 뷰어 주소의
    접수번호(rcpNo)로 찾는다.
    """
    wanted = {url for url in urls if url}
    if not wanted:
        return {}
    found: dict[str, int] = {}
    keys: dict[str, list[str]] = {}
    for url in wanted:
        keys.setdefault(canonical_url(url), []).append(url)
    for key, card_id in (await session.execute(
        select(News.canonical_url, SourceCard.id)
        .join(SourceCard, SourceCard.news_id == News.id)
        .where(News.canonical_url.in_(keys))
    )).all():
        found.update(dict.fromkeys(keys[key], card_id))
    for url, card_id in (await session.execute(
        select(TelegramMessage.url, SourceCard.id)
        .join(SourceCard, SourceCard.telegram_message_id == TelegramMessage.id)
        .where(TelegramMessage.url.in_(wanted))
    )).all():
        found[url] = card_id
    receipts: dict[str, list[str]] = {}
    for url in wanted:
        if rcept_no := _dart_rcept_no(url):
            receipts.setdefault(rcept_no, []).append(url)
    if receipts:
        for rcept_no, card_id in (await session.execute(
            select(DartDisclosure.rcept_no, SourceCard.id)
            .join(SourceCard, SourceCard.dart_disclosure_id == DartDisclosure.id)
            .where(DartDisclosure.rcept_no.in_(receipts))
        )).all():
            found.update(dict.fromkeys(receipts[rcept_no], card_id))
    return found


def _dart_rcept_no(url: str) -> str | None:
    """DART 공시 뷰어 주소(…/dsaf001/main.do?rcpNo=…)의 접수번호. 공시 주소가 아니면 None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = parts.hostname or ""
    if (parts.scheme not in {"http", "https"}
            or not (host == "dart.fss.or.kr" or host.endswith(".dart.fss.or.kr"))
            or parts.path != "/dsaf001/main.do"):
        return None
    return (parse_qs(parts.query).get("rcpNo") or [None])[0]
