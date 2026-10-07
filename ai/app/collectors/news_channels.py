"""증권사 텔레그램 채널의 메시지와, 메시지에 걸린 뉴스 링크 본문을 모은다. 로그인이 필요 없다.

    uv run python -m app.collectors.news_channels                        # 어제 0시부터, 범위의 채널 전부
    uv run python -m app.collectors.news_channels --channel skitteam --max-pages 1
    uv run python -m app.collectors.news_channels --show-links           # 연 링크를 하나씩 본다
    uv run python -m app.collectors.news_channels --dry-run              # DB 에 쓰지 않고 요약만
    uv run python -m app.collectors.news_channels --jsonl                # JSONL 파일 사본도 쓴다

    ① 수집 범위를 확인한다 (collection_scope.toml: 채널·기간·수집량)     core/scope.py
    ② 채널마다 t.me/s/ 페이지를 넘기며 기간 안 메시지를 모은다        services/telegram_web
    ③ 수집량 상한 안의 메시지만 남긴다. 이미 저장된 메시지는 갱신만 한다
    ④ 게시 24시간 이내 메시지의 링크를 연다 (LLM 호출 없음)            services/news_link
       telegram_link 가 켜져 있을 때만, 남은 수집량만큼만 연다
    ⑤ DB 에 넣는다 (save_to_db)
         메시지 → telegram_messages, 연 기사 → news, 메시지의 링크 하나하나 → telegram_message_links
         그다음 공통 자료 ID(source_card)가 없는 원문에 카드를 만든다

**범위 밖은 받지 않는다.** 모든 자료를 계속 쌓는 것을 기본으로 삼지 않는다.
범위가 비어 있으면 아무것도 수집하지 않는다.

JSONL 파일은 --jsonl 일 때만 쓴다(data/telegram/, git 에 올라가지 않는다). DB 밖의 사본이라
보관 정책으로 본문을 지울 때 함께 지워지지 않는다. 기사 전문은 파일에 들어가지 않고
DB(news.cleaned_text)에만 들어간다.

다시 수집하면 같은 메시지·기사는 행이 늘지 않는다. 처음 저장한 메시지 본문과 성공한 기사
본문은 바꾸지 않고, 실패했던 링크만 이번 결과로 채운다(repositories/telegram_message.py·news.py).
24시간 규칙 안이면 다음 실행이 실패한 링크를 다시 여는 셈이다.

**24시간이 지난 메시지의 링크는 열지 않는다.** 기사는 발행 뒤에도 고쳐진다. 보고서는 대상일
이후에 나온 정보를 쓰지 않도록 기준 시각(컷오프)을 두는데, 며칠 지나 링크를 열면 그사이 고쳐진
기사를 읽게 되어 기준 시각 이후의 정보가 본문을 타고 들어온다.

증권사 리포트 PDF 를 받는 collectors/telegram.py 와는 다르다. 그쪽은 로그인한 계정으로
Telethon 을 쓴다.
"""

import argparse
import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.database import SessionLocal
from app.core.scope import CollectionScope, ScopeError, load_scope
from app.repositories.news import save_news
from app.repositories.scope import count_collected
from app.repositories.source_card import register_missing_sources
from app.repositories.telegram_message import (
    ensure_channels,
    known_message_keys,
    save_message_links,
    save_messages,
)
from app.services.news_link import LinkBody, fetch_link_bodies, is_fetchable
from app.services.news_link.fetch import DEFAULT_TIMEOUT_SEC as LINK_TIMEOUT_SEC
from app.services.telegram_web import Channel, ChannelMessage, fetch_channel, select_channels
from app.services.telegram_web.fetch import DEFAULT_MAX_PAGES, DEFAULT_PAGE_DELAY_SEC

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 며칠 전 0시부터 모을지. 1 이면 어제 0시부터 지금까지, 0 이면 오늘 0시부터다.
DEFAULT_DAYS = 1
# 게시된 지 이보다 오래된 메시지의 링크는 열지 않는다(맨 위 설명). 링크를 여는 지금이 기준이다.
LINK_MAX_AGE = timedelta(hours=24)
# 메시지 하나에서 여는 링크 수. 뉴스 제목을 여러 개 묶어 올리는 글이 있어서(skitteam 은
# 한 페이지 12건에 링크 53개였다) 다 열면 링크가 몇 배가 된다. 상한 때문에 건너뛴 수는
# 출력에 남기고, 상한을 늘릴지는 그 수를 보고 정한다. 0 이면 상한 없이 연다.
DEFAULT_LINKS_PER_MESSAGE = 3
# 채널 페이지 요청 타임아웃. 채널 페이지는 몇 번 안 열어서 링크 타임아웃(LINK_TIMEOUT_SEC)보다
# 넉넉히 준다.
PAGE_TIMEOUT_SEC = 20.0
# 결과 폴더. 실행한 위치 기준 상대 경로라 ai/ 에서 실행하면 ai/data/telegram/ 이 된다.
DEFAULT_OUT = Path("data/telegram")
# --show-links 에서 메시지·발췌를 보여줄 글자 수
PREVIEW_CHARS = 80
# 정렬 키에서 None 대신 쓰는 값. datetime 과 None 은 크기를 비교할 수 없어서 넣는다.
# 게시 시각을 모르는 메시지를 맨 뒤로 보내는 것은 정렬 키의 첫 항목(posted_at is None)이 한다.
_NO_TIME = datetime.min.replace(tzinfo=KST)
# news 로 저장하지 않는 링크 결과. PDF·이미지는 기사가 아니고, blocked 는 가지 않은 주소다.
# 이런 링크는 telegram_message_links 에만 남는다.
NOT_ARTICLE = frozenset({"pdf", "not_html", "blocked"})
# 칼럼 길이(telegram_messages.author·views, news.publisher). 넘으면 저장이 통째로 실패하므로 자른다.
AUTHOR_MAX_CHARS = 200
VIEWS_MAX_CHARS = 32
PUBLISHER_MAX_CHARS = 100


@dataclass
class LinkChoice:
    """메시지 하나에서 무엇을 열지."""

    urls: list[str] = field(default_factory=list)
    skipped: int = 0  # 메시지당 상한을 넘어 건너뜀
    junk: int = 0  # 주소가 아니라 티커 문자열("PLTR.US")이 링크로 잡힌 것
    stale: bool = False  # 게시 24시간이 지났거나 게시 시각을 몰라서 열지 않음


@dataclass
class ChannelStats:
    """채널 하나의 수집 집계. 실행이 끝나면 summary_lines() 가 출력한다."""

    channel: Channel
    pages: int = 0  # 요청한 채널 페이지 수
    truncated: bool = False  # 페이지 상한에 닿아 구간을 다 못 읽었다 (fetch_channel 의 truncated)
    messages: int = 0  # 구간 안 메시지 수 (게시 시각을 모르는 것은 undated 로 따로 센다)
    undated: int = 0  # 게시 시각을 못 읽은 메시지
    with_links: int = 0  # 외부 링크가 하나라도 걸린 메시지
    stale: int = 0  # 링크가 있지만 24시간이 지났거나 게시 시각을 몰라서 열지 않은 메시지
    opened: int = 0  # 열기로 고른 링크. 같은 주소도 메시지마다 센다 (실제 요청은 주소당 한 번)
    skipped: int = 0  # 메시지당 상한을 넘어 건너뛴 링크
    junk: int = 0  # 주소가 아니라 티커 문자열이라 열지 않은 링크
    hidden: int = 0  # 보이는 주소와 달라서 쓰지 않은 실제 링크 (telegram_web/parse.py 참고)
    error: str | None = None  # 채널 페이지를 읽다 실패한 사유 (fetch_channel 의 error)


def choose_links(
    message: ChannelMessage,
    *,
    now: datetime,
    max_age: timedelta = LINK_MAX_AGE,
    per_message: int = DEFAULT_LINKS_PER_MESSAGE,
) -> LinkChoice:
    """메시지 하나에서 열 링크를 고른다.

    티커 문자열은 빼고(junk), 게시 24시간이 지났거나 게시 시각을 모르면 하나도 열지 않고
    (stale), 남은 것 중 앞에서부터 per_message 개만 연다(넘친 것은 skipped).
    """
    fetchable = [url for url in message.links if is_fetchable(url)]
    choice = LinkChoice(junk=len(message.links) - len(fetchable))
    if not fetchable:
        return choice
    # 게시 시각을 모르면 24시간 안인지도 모른다. 열지 않는 쪽이 안전하다.
    if message.posted_at is None or now - message.posted_at > max_age:
        choice.stale = True
        return choice
    choice.urls = fetchable if per_message <= 0 else fetchable[:per_message]
    choice.skipped = len(fetchable) - len(choice.urls)
    return choice


async def attach_link_bodies(
    messages: list[ChannelMessage],
    stats: list[ChannelStats],
    *,
    now: datetime,
    per_message: int,
    max_links: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """메시지마다 열 링크를 고르고, 모은 주소를 한꺼번에 열어 각 메시지의 link_bodies 에 붙인다.

    messages 와 stats 를 직접 고친다. 채널별 집계(stale·opened·skipped·junk)도 여기서 채운다.
    max_links 를 주면 주소를 그 수까지만 연다(수집 범위의 수집량 상한). 고르고도 상한 때문에
    열지 않은 주소 수를 돌려준다. 그 링크는 link_bodies 에 없고 DB 에는 out_of_scope 로 남는다.
    """
    by_channel = {stat.channel.id: stat for stat in stats}
    chosen: list[tuple[ChannelMessage, LinkChoice]] = []
    for message in messages:
        if not message.links:
            continue
        choice = choose_links(message, now=now, per_message=per_message)
        stat = by_channel[message.channel]
        stat.stale += int(choice.stale)
        stat.opened += len(choice.urls)
        stat.skipped += choice.skipped
        stat.junk += choice.junk
        chosen.append((message, choice))

    # 같은 기사를 여러 채널이 올리는 일이 흔하다. 한 번만 열고 나눠 쓴다.
    urls = list(dict.fromkeys(url for _message, choice in chosen for url in choice.urls))
    held = 0
    if max_links is not None and len(urls) > max_links:
        held = len(urls) - max_links
        urls = urls[:max(max_links, 0)]
    if not urls:
        return held
    logger.info("링크 %d개를 연다", len(urls))
    async with httpx.AsyncClient(timeout=LINK_TIMEOUT_SEC, transport=transport) as client:
        bodies = await fetch_link_bodies(urls, client=client)
    by_url = dict(zip(urls, bodies, strict=True))
    for message, choice in chosen:
        message.link_bodies = [by_url[url] for url in choice.urls if url in by_url]
    return held


async def read_channels(
    channels: tuple[Channel, ...],
    *,
    since: datetime,
    until: datetime,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay: float = DEFAULT_PAGE_DELAY_SEC,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[ChannelMessage], list[ChannelStats]]:
    """채널을 차례로 읽어 (메시지 목록, 채널별 집계) 를 돌려준다. 링크는 열지 않는다.

    메시지는 게시 시각순이고, 시각을 모르는 것은 맨 뒤에 둔다. 채널 하나가 실패해도 예외를
    던지지 않는다. 실패는 ChannelStats.error 에 남는다.
    """
    messages: list[ChannelMessage] = []
    stats: list[ChannelStats] = []
    async with httpx.AsyncClient(timeout=PAGE_TIMEOUT_SEC, transport=transport) as page_client:
        for i, channel in enumerate(channels):
            if i:
                await asyncio.sleep(page_delay)  # 채널이 달라도 같은 t.me 서버라 채널 사이에도 쉰다
            got = await fetch_channel(
                page_client, channel.id, since=since, until=until,
                max_pages=max_pages, page_delay=page_delay,
            )
            found = got.messages + got.undated
            stats.append(ChannelStats(
                channel=channel, pages=got.pages, messages=len(got.messages),
                undated=len(got.undated), with_links=sum(bool(m.links) for m in found),
                hidden=sum(len(m.hidden_links) for m in found), error=got.error,
                truncated=got.truncated,
            ))
            logger.info("%s: 페이지 %d, 메시지 %d건%s%s", channel.id, got.pages, len(got.messages),
                        " (페이지 상한에 닿음)" if got.truncated else "",
                        f" (실패: {got.error})" if got.error else "")
            messages += found
    messages.sort(key=lambda m: (m.posted_at is None, m.posted_at or _NO_TIME, m.channel))
    return messages, stats


async def collect(
    channels: tuple[Channel, ...],
    *,
    since: datetime,
    until: datetime,
    now: datetime,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay: float = DEFAULT_PAGE_DELAY_SEC,
    open_links: bool = True,
    per_message: int = DEFAULT_LINKS_PER_MESSAGE,
    max_links: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[ChannelMessage], list[ChannelStats]]:
    """채널을 읽고(read_channels) 링크를 연다(open_links). 수집 범위는 보지 않는다 — run() 이 본다.

    `now` 를 until 과 따로 받는 것은 24시간 규칙이 **링크를 여는 지금**을 기준으로 해서다.
    `transport` 는 테스트가 가짜 서버를 끼우려고 받는다.
    """
    messages, stats = await read_channels(
        channels, since=since, until=until, max_pages=max_pages, page_delay=page_delay,
        transport=transport,
    )
    if open_links:
        await attach_link_bodies(messages, stats, now=now, per_message=per_message,
                                 max_links=max_links, transport=transport)
    return messages, stats


def write_jsonl(messages: list[ChannelMessage], out_dir: Path, collected_at: datetime) -> Path:
    """메시지를 한 줄에 하나씩 JSON 으로 쓰고(JSON Lines) 파일 경로를 돌려준다.

    파일 이름에 수집 시각이 들어가서 실행할 때마다 새 파일이 생긴다. 기사는 앞부분
    발췌(LinkBody.excerpt)만 들어간다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"messages-{collected_at:%Y%m%d-%H%M%S}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for message in messages:
            f.write(message.model_dump_json() + "\n")
    return path


def link_plan(
    message: ChannelMessage, *, now: datetime, per_message: int, unopened: str = "out_of_scope"
) -> list[tuple[str, str, LinkBody | None]]:
    """메시지의 링크마다 (적힌 주소, 상태, 연 결과). 메시지 안 순서 그대로다.

    연 링크는 LinkBody.status 를, 열지 않은 링크는 그 이유를 상태로 쓴다. 어떤 링크를 열지는
    choose_links 가 정했으므로 collect() 와 같은 now·per_message 로 다시 불러 그 판단을 재현한다.
    열기로 골랐는데 결과가 없는 링크는 unopened 다 — 수집 범위 때문에 열지 않았으면
    out_of_scope, --no-links 로 돌렸으면 not_opened. 열지 않은 링크도 버리지 않는다 — 발견했다는
    사실이 출처다.
    """
    choice = choose_links(message, now=now, per_message=per_message)
    bodies = {body.url: body for body in message.link_bodies}
    plan = []
    for url in message.links:
        body = bodies.get(url)
        if body is not None:
            status = body.status
        elif not is_fetchable(url):
            status = "not_fetchable"
        elif choice.stale:
            status = "stale"
        elif url not in choice.urls:
            status = "over_limit"
        else:
            status = unopened
        plan.append((url, status, body))
    return plan


def _body_error(body: LinkBody) -> str:
    """news.body_error 에 남길 사유. 링크 결과 종류를 앞에 붙인다."""
    if body.status == "http_error":
        return f"http_error: {body.http_status}"
    if body.status == "ok":
        return "ok: 본문 전체(text)가 넘어오지 않음"
    return f"{body.status}: {body.error}" if body.error else body.status


def news_row(body: LinkBody) -> dict | None:
    """연 링크 → news 행. 기사가 아니거나(PDF 등) 도착한 주소를 모르면 None.

    본문은 기사 전체(LinkBody.text)다. 앞 3문장 발췌(excerpt)를 넣지 않는다.
    발행 시각은 모르므로 비워 둔다. 링크를 연 시각이나 메시지 게시 시각으로 채우지 않는다.
    """
    if body.final_url is None or body.status in NOT_ARTICLE:
        return None
    ok = body.status == "ok" and bool(body.text)
    host = (body.domain or urlparse(body.final_url).netloc).lower().removeprefix("www.")
    return {
        "url": body.final_url,
        "title": body.title or "",
        "publisher": host[:PUBLISHER_MAX_CHARS],
        "source": "telegram",
        "published_at": None,
        "summary": "",
        "cleaned_text": body.text if ok else None,
        "body_status": "ok" if ok else "failed",
        "body_error": None if ok else _body_error(body),
        "body_fetched_at": body.fetched_at,
        "body_extractor": "news_link",
    }


def message_row(message: ChannelMessage, channel_id: int) -> dict:
    """telegram_messages 행. 본문은 채널에 보이는 글자 그대로다."""
    return {
        "channel_id": channel_id,
        "msg_id": message.msg_id,
        "url": message.url or f"https://t.me/{message.channel}/{message.msg_id}",
        "posted_at": message.posted_at,
        "author": message.author[:AUTHOR_MAX_CHARS] if message.author else None,
        "text": message.text,
        "attachment_name": message.attachment,
        "forwarded_from": message.forwarded_from,
        "forwarded_from_url": message.forwarded_from_url,
        "hidden_links": message.hidden_links,
        "views": message.views[:VIEWS_MAX_CHARS] if message.views else None,
        "edited": message.edited,
        "collected_via": "web",
    }


@dataclass
class DbStats:
    """DB 저장 집계. db_summary_lines() 가 출력한다."""

    messages_new: int = 0
    messages_known: int = 0  # 이미 저장돼 있던 메시지
    edits_detected: int = 0  # 처음 저장한 본문과 글자가 달랐던 메시지. 본문은 그대로 뒀다
    no_msg_id: int = 0  # 메시지 번호를 못 읽어 저장하지 않은 메시지
    news_new: int = 0
    news_filled: int = 0  # 실패했던 본문을 이번에 채운 기사
    links_new: int = 0
    links_updated: int = 0  # 실패했던 링크를 이번 결과로 바꾼 것
    cards: dict[str, int] = field(default_factory=dict)  # 새로 만든 공통 자료 ID
    register_error: str | None = None  # 공통 자료 ID 등록 실패. 원문은 저장됐다


async def save_to_db(
    messages: list[ChannelMessage],
    channels: tuple[Channel, ...],
    *,
    now: datetime,
    per_message: int,
    unopened: str = "out_of_scope",
    session_factory=SessionLocal,
) -> DbStats:
    """collect() 결과를 DB 에 넣는다. 원문(메시지·기사·링크)은 한 트랜잭션이다.

    공통 자료 ID 등록은 원문을 커밋한 뒤 따로 한다. 등록이 실패해도 원문은 남고,
    `python -m app.collectors.sources register` 로 다시 돌리면 된다.
    """
    stats = DbStats()
    keyed = [m for m in messages if m.msg_id is not None]
    stats.no_msg_id = len(messages) - len(keyed)
    async with session_factory() as session:
        channel_ids = await ensure_channels(session, [
            {"telegram_handle": c.id, "name": c.name, "is_public": True} for c in channels
        ])
        saved = await save_messages(
            session, [message_row(m, channel_ids[m.channel]) for m in keyed]
        )
        stats.messages_new = sum(s.inserted for s in saved)
        stats.messages_known = len(saved) - stats.messages_new
        stats.edits_detected = sum(s.text_changed for s in saved)

        # 같은 기사를 여러 메시지가 공유한다. 연 결과(주소당 하나)마다 한 번만 저장한다.
        bodies = list({body.url: body for m in keyed for body in m.link_bodies}.values())
        articles = [(body, row) for body in bodies if (row := news_row(body)) is not None]
        news = await save_news(session, [row for _body, row in articles])
        stats.news_new, stats.news_filled = news.inserted, news.filled
        news_ids = {body.url: news_id for (body, _row), news_id in zip(articles, news.ids,
                                                                       strict=True)}

        link_rows = []
        for message, result in zip(keyed, saved, strict=True):
            if result.text_changed:
                continue  # 처음 저장한 본문의 링크를 그대로 둔다
            plan = link_plan(message, now=now, per_message=per_message, unopened=unopened)
            for position, (url, status, body) in enumerate(plan, start=1):
                link_rows.append({
                    "message_id": result.id,
                    "kind": "url",
                    "position": position,
                    "discovered_url": url,
                    "final_url": body.final_url if body else None,
                    "status": status,
                    "error": body.error if body else None,
                    "http_status": body.http_status if body else None,
                    "fetched_at": body.fetched_at if body else None,
                    "news_id": news_ids.get(url),
                    "analyst_report_id": None,
                })
        stats.links_new, stats.links_updated = await save_message_links(session, link_rows)
        await session.commit()

    try:
        async with session_factory() as session:
            stats.cards = await register_missing_sources(session)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — 원문은 이미 커밋됐다. 실패만 알리고 다시 돌리게 한다
        stats.register_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    return stats


def db_summary_lines(stats: DbStats) -> list[str]:
    lines = [
        f"DB 저장: 메시지 새로 {stats.messages_new}건 · 이미 있던 것 {stats.messages_known}건"
        + (f" (본문이 달라진 것 {stats.edits_detected}건 — 처음 본문 유지)"
           if stats.edits_detected else ""),
        (f"         기사 새로 {stats.news_new}건 · 본문 보완 {stats.news_filled}건 · "
         f"링크 새로 {stats.links_new}개 · 결과 갱신 {stats.links_updated}개"),
    ]
    if stats.no_msg_id:
        lines.append(f"         메시지 번호를 못 읽어 저장하지 않은 것 {stats.no_msg_id}건")
    if stats.register_error:
        lines.append(f"         공통 자료 ID 등록 실패: {stats.register_error} "
                     "(원문은 저장됨. `python -m app.collectors.sources register` 로 다시 등록)")
    else:
        lines.append("         공통 자료 ID 새로 " + " · ".join(
            f"{kind} {n}" for kind, n in stats.cards.items()))
    return lines


@dataclass
class RunResult:
    """run() 의 결과. 범위 때문에 받지 않은 것도 센다."""

    messages: list[ChannelMessage]  # 범위 안이라 저장 대상이 된 메시지
    stats: list[ChannelStats]
    held_messages: int = 0  # 수집량 상한(telegram_web.max_items) 때문에 저장하지 않은 새 메시지
    held_undated: int = 0  # 오늘이 기간 밖이라 받지 않은 게시 시각 불명 메시지
    held_links: int = 0  # 범위 때문에 열지 않은 링크 주소 (telegram_link 꺼짐·상한)
    jsonl: Path | None = None
    db: DbStats | None = None


async def run(
    channels: tuple[Channel, ...],
    *,
    scope: CollectionScope,
    since: datetime,
    until: datetime,
    now: datetime,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay: float = DEFAULT_PAGE_DELAY_SEC,
    per_message: int = DEFAULT_LINKS_PER_MESSAGE,
    no_links: bool = False,
    dry_run: bool = False,
    jsonl_dir: Path | None = None,
    session_factory=SessionLocal,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RunResult:
    """수집 범위 안에서 채널을 읽고, 링크를 열고, 저장한다. 범위 밖이면 ScopeError.

        채널      telegram_web.channels 에 있어야 한다
        기간      [since, until] 을 범위 기간으로 자른다. 게시 시각 불명 메시지는 기간 안인지
                  모르므로 오늘이 기간 안일 때만 받는다
        수집량    이미 저장된 메시지는 갱신만 하고, 새 메시지는 telegram_web.max_items 까지만 받는다
        링크      telegram_link 가 꺼져 있으면 열지 않고, 켜져 있으면 남은 수집량만큼만 연다.
                  못 연 링크는 발견 기록에 out_of_scope 로 남는다
    """
    web = scope.require("telegram_web")
    web.check(channel.id for channel in channels)
    window = scope.window(since, until)
    if window is None:
        raise ScopeError(f"수집 기간({scope.start}~{scope.end}) 밖이다. 받을 메시지가 없다.")

    messages, stats = await read_channels(
        channels, since=window[0], until=window[1], max_pages=max_pages, page_delay=page_delay,
        transport=transport,
    )
    result = RunResult(messages=[], stats=stats)
    if not scope.contains(now.astimezone(KST).date()):
        result.held_undated = sum(m.posted_at is None for m in messages)
        messages = [m for m in messages if m.posted_at is not None]

    links = scope.source("telegram_link")
    async with session_factory() as session:
        known = await known_message_keys(
            session, [(m.channel, m.msg_id) for m in messages if m.msg_id is not None]
        )
        budget = web.remaining(await count_collected(session, "telegram_web"))
        link_budget = (links.remaining(await count_collected(session, "telegram_link"))
                       if links.enabled else 0)
    for message in messages:
        is_new = message.msg_id is not None and (message.channel, message.msg_id) not in known
        if is_new and budget <= 0:
            result.held_messages += 1
            continue
        budget -= int(is_new)
        result.messages.append(message)

    if not no_links:
        result.held_links = await attach_link_bodies(
            result.messages, stats, now=now, per_message=per_message, max_links=link_budget,
            transport=transport,
        )
    if jsonl_dir is not None:
        result.jsonl = write_jsonl(result.messages, jsonl_dir, now)
    if not dry_run:
        result.db = await save_to_db(
            result.messages, channels, now=now, per_message=per_message,
            unopened="not_opened" if no_links else "out_of_scope",
            session_factory=session_factory,
        )
    return result


def scope_lines(result: RunResult) -> list[str]:
    """범위 때문에 받지 않은 것. 없으면 빈 목록."""
    held = [
        (result.held_messages, "수집량 상한으로 저장하지 않은 새 메시지 {}건"),
        (result.held_undated, "오늘이 수집 기간 밖이라 받지 않은 게시 시각 불명 메시지 {}건"),
        (result.held_links, "수집 범위 때문에 열지 않은 링크 {}개"),
    ]
    return [f"범위: {text.format(n)}" for n, text in held if n]


def summary_lines(messages: list[ChannelMessage], stats: list[ChannelStats]) -> list[str]:
    """실행 끝에 찍는 요약. 채널마다 두세 줄을 쓰고, 그 아래에 연 링크 전체의 결과를 모아 붙인다."""
    lines = []
    for s in stats:
        head = f"[{s.channel.id}] {s.channel.affiliation} · 페이지 {s.pages} · 메시지 {s.messages}건"
        if s.undated:
            head += f" (게시 시각 못 읽음 {s.undated}건)"
        if s.truncated:
            head += " · 페이지 상한에 닿아 구간 앞부분을 못 읽었을 수 있음 (--max-pages 로 늘린다)"
        if s.error:
            head += f" · 실패: {s.error}"
        lines.append(head)
        lines.append(f"    링크 있는 메시지 {s.with_links}건 · 연 링크 {s.opened}개 · "
                     f"상한으로 건너뜀 {s.skipped}개 · 24시간 지나 안 연 메시지 {s.stale}건")
        if s.hidden:
            lines.append(f"    보이는 주소와 실제 링크가 달랐던 것 {s.hidden}개 — 보이는 주소를 썼다")

    # 같은 주소는 한 번만 센다
    bodies = list({body.url: body for m in messages for body in m.link_bodies}.values())
    if not bodies:
        lines.append("\n연 링크가 없습니다.")
        return lines
    status = Counter(body.status for body in bodies)
    codes = Counter(body.http_status for body in bodies if body.status == "http_error")
    resolved = sum(1 for body in bodies if body.domain)
    unshortened = sum(1 for body in bodies if body.final_url and body.final_url != body.url)
    ok = [body for body in bodies if body.status == "ok"]
    domains = Counter(body.domain for body in bodies if body.domain)

    lines.append(f"\n링크 {len(bodies)}개 (중복 제외)")
    lines.append("  결과      " + " · ".join(f"{k} {v}" for k, v in status.most_common()))
    if codes:
        lines.append("  HTTP 오류 " + ", ".join(f"{code}×{n}" for code, n in codes.most_common()))
    lines.append(f"  최종 주소 {resolved}/{len(bodies)} 알아냄 (리다이렉트로 주소가 바뀐 것 {unshortened})")
    if ok:
        avg = sum(body.chars for body in ok) / len(ok)
        lines.append(f"  본문 확보 {len(ok)}개 · 발췌 평균 {avg:.0f}자")
    lines.append("  도메인    " + ", ".join(f"{d} {n}" for d, n in domains.most_common(6)))
    return lines


def link_lines(messages: list[ChannelMessage]) -> list[str]:
    """--show-links 출력. 메시지 앞부분 밑에 그 메시지에서 연 기사들을 보여준다.

    단축 URL 이 엉뚱한 기사로 열리지 않았는지 눈으로 확인하려는 것이다.
    """
    lines = []
    for message in messages:
        if not message.link_bodies:
            continue
        when = f"{message.posted_at:%m-%d %H:%M}" if message.posted_at else "??"
        head = message.text.replace("\n", " ")[:PREVIEW_CHARS]
        lines.append(f"\n{message.channel}/{message.msg_id} {when}  {head}")
        if message.hidden_links:
            lines.append(f"  (보이는 주소와 달라 쓰지 않은 실제 링크: {', '.join(message.hidden_links)})")
        for body in message.link_bodies:
            reason = body.error or (f"HTTP {body.http_status}" if body.http_status else "")
            lines.append(f"  [{body.status}] {body.domain or body.url}"
                         + (f" ({reason})" if reason else "")
                         + (f" · {body.title}" if body.title else ""))
            if body.excerpt:
                lines.append("      " + body.excerpt.replace("\n", " ")[:PREVIEW_CHARS])
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description="증권사 텔레그램 채널의 메시지·뉴스 링크 수집 (로그인 불필요)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help=f"며칠 전 0시부터 모을지 (기본 {DEFAULT_DAYS}). 수집 범위 기간 밖은 받지 않는다")
    p.add_argument("--channel", action="append",
                   help="채널 아이디. 여러 번 줄 수 있다. 기본은 수집 범위의 채널 전부")
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                   help=f"채널당 최대 페이지 (기본 {DEFAULT_MAX_PAGES})")
    p.add_argument("--links-per-message", type=int, default=DEFAULT_LINKS_PER_MESSAGE,
                   help=f"메시지 하나에서 열 링크 수 (기본 {DEFAULT_LINKS_PER_MESSAGE}, 0 이면 전부)")
    p.add_argument("--no-links", action="store_true", help="링크를 열지 않는다")
    p.add_argument("--show-links", action="store_true", help="연 링크를 메시지와 나란히 보여준다")
    p.add_argument("--dry-run", action="store_true",
                   help="DB 에 쓰지 않는다. 수집 범위 확인과 요약만 본다")
    p.add_argument("--jsonl", action="store_true",
                   help="JSONL 파일 사본도 쓴다(--out). DB 밖의 사본이라 보관 정책으로 지울 때 따로 지운다")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="--jsonl 파일을 쓸 폴더")
    args = p.parse_args()
    if args.days < 0 or args.max_pages < 1:
        p.error("--days 는 0 이상, --max-pages 는 1 이상이어야 한다")
    try:
        scope = load_scope()
        web = scope.require("telegram_web")
        channels = select_channels(args.channel or sorted(web.allowed))
    except (ScopeError, ValueError) as exc:
        p.exit(1, f"{exc}\n")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # httpx 는 INFO 에서 요청마다 한 줄을 찍는다. 링크 수십 개면 요약이 묻힌다.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    now = datetime.now(KST)
    # 수집 구간은 N일 전 0시(KST)부터 지금까지다. 24시간 규칙의 기준도 같은 now 를 쓴다.
    # run() 이 이 구간을 수집 범위의 기간으로 한 번 더 자른다.
    since = (now - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"수집 구간: {since:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} (KST) · 채널 {len(channels)}개"
          f" · 범위 기간 {scope.start} ~ {scope.end}")
    try:
        result = asyncio.run(run(
            channels, scope=scope, since=since, until=now, now=now, max_pages=args.max_pages,
            per_message=args.links_per_message, no_links=args.no_links, dry_run=args.dry_run,
            jsonl_dir=args.out if args.jsonl else None,
        ))
    except ScopeError as exc:
        p.exit(1, f"{exc}\n")
    except Exception as exc:  # noqa: BLE001 — 무엇이 실패했는지만 알린다
        p.exit(1, f"수집·저장 실패: {type(exc).__name__}: {str(exc)[:200]}\n"
                  "  ai/ 에서 `uv run alembic upgrade head` 를 했는지 확인하세요.\n")

    print("\n".join(summary_lines(result.messages, result.stats)))
    if args.show_links:
        print("\n".join(link_lines(result.messages)))
    for line in scope_lines(result):
        print(line)
    if result.jsonl:
        print(f"\n파일 사본: {result.jsonl} ({len(result.messages)}건)")
    if result.db:
        print("\n".join(db_summary_lines(result.db)))
    elif args.dry_run:
        print("\n--dry-run: DB 에 쓰지 않았다")

    failed = [s.channel.id for s in result.stats if s.error]
    if failed:
        p.exit(1, f"채널 수집 실패: {', '.join(failed)}. 위의 실패 사유를 확인하세요.\n")
    if result.db is not None and result.db.register_error:
        p.exit(1, "공통 자료 ID 등록에 실패했다. 위의 사유를 확인하세요.\n")


if __name__ == "__main__":
    main()
