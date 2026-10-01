"""증권사 텔레그램 채널의 메시지와, 메시지에 걸린 뉴스 링크 본문을 모은다. 로그인이 필요 없다.

    uv run python -m app.collectors.news_channels                        # 어제 0시부터, 채널 전부
    uv run python -m app.collectors.news_channels --channel skitteam --max-pages 1
    uv run python -m app.collectors.news_channels --show-links           # 연 링크를 하나씩 본다

    ① 채널마다 t.me/s/ 페이지를 넘기며 구간 안 메시지를 모은다   services/telegram_web
    ② 게시 24시간 이내 메시지의 링크를 연다 (LLM 호출 없음)       services/news_link
    ③ data/telegram/messages-<수집시각>.jsonl 에 쓴다

DB 에 넣지 않는다. 메시지·기사를 어느 표에 얼마나 둘지(원문 보관 기간)를 아직 팀에서
정하지 않았다. 그때까지는 파일로 쌓고 눈으로 확인한다. data/ 는 git 에 올라가지 않는다.

**24시간이 지난 메시지의 링크는 열지 않는다.** 기사는 발행 뒤에도 고쳐진다. 며칠 지나 열면
그때의 기사를 읽게 되고, 보고서가 컷오프로 막아둔 사후 정보가 본문을 타고 들어온다.

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

import httpx

from app.services.news_link import fetch_link_bodies, is_fetchable
from app.services.news_link.fetch import DEFAULT_TIMEOUT_SEC as LINK_TIMEOUT_SEC
from app.services.telegram_web import Channel, ChannelMessage, fetch_channel, select_channels
from app.services.telegram_web.fetch import DEFAULT_MAX_PAGES, DEFAULT_PAGE_DELAY_SEC

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

DEFAULT_DAYS = 1
# 이보다 오래된 메시지의 링크는 열지 않는다(위 설명).
LINK_MAX_AGE = timedelta(hours=24)
# 메시지 하나에서 여는 링크 수. 뉴스 제목을 여러 개 묶어 올리는 글이 있어서(skitteam 은
# 한 페이지 12건에 링크 53개였다) 다 열면 링크가 몇 배가 된다. 건너뛴 수를 출력에 남겨
# 늘릴지는 데이터로 정한다. 0 이면 상한 없이 연다.
DEFAULT_LINKS_PER_MESSAGE = 3
# 채널 페이지 요청 타임아웃. 채널 페이지는 몇 번 안 열어서 링크보다 넉넉히 준다.
PAGE_TIMEOUT_SEC = 20.0
DEFAULT_OUT = Path("data/telegram")
# --show-links 에서 발췌를 보여줄 글자 수
PREVIEW_CHARS = 80
# 게시 시각을 모르는 메시지를 정렬할 때 쓰는 자리 채움. 그런 메시지는 맨 뒤로 보낸다.
_NO_TIME = datetime.min.replace(tzinfo=KST)


@dataclass
class LinkChoice:
    """메시지 하나에서 무엇을 열지."""

    urls: list[str] = field(default_factory=list)
    skipped: int = 0  # 메시지당 상한을 넘어 건너뜀
    junk: int = 0  # 주소가 아니라 티커 문자열("PLTR.US")이 링크로 잡힌 것
    stale: bool = False  # 게시 24시간이 지났거나 게시 시각을 몰라서 열지 않음


@dataclass
class ChannelStats:
    channel: Channel
    pages: int = 0
    messages: int = 0
    undated: int = 0
    with_links: int = 0  # 외부 링크가 하나라도 걸린 메시지
    stale: int = 0  # 링크가 있지만 24시간이 지나 열지 않은 메시지
    opened: int = 0  # 연 링크
    skipped: int = 0  # 메시지당 상한을 넘어 건너뛴 링크
    junk: int = 0
    hidden: int = 0  # 보이는 주소와 달라서 쓰지 않은 실제 링크 (telegram_web/parse.py 참고)
    error: str | None = None


def choose_links(
    message: ChannelMessage,
    *,
    now: datetime,
    max_age: timedelta = LINK_MAX_AGE,
    per_message: int = DEFAULT_LINKS_PER_MESSAGE,
) -> LinkChoice:
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


async def _attach_link_bodies(
    messages: list[ChannelMessage],
    stats: list[ChannelStats],
    *,
    now: datetime,
    per_message: int,
    client: httpx.AsyncClient,
) -> None:
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
    if not urls:
        return
    logger.info("링크 %d개를 연다", len(urls))
    bodies = await fetch_link_bodies(urls, client=client)
    by_url = dict(zip(urls, bodies, strict=True))
    for message, choice in chosen:
        message.link_bodies = [by_url[url] for url in choice.urls]


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
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[ChannelMessage], list[ChannelStats]]:
    """메시지(게시 시각순, 시각 모르는 것은 맨 뒤)와 채널별 집계. 예외를 던지지 않는다.

    `now` 를 until 과 따로 받는 것은 24시간 규칙이 **링크를 여는 지금**을 기준으로 해서다.
    `transport` 는 테스트가 가짜 서버를 끼우려고 받는다.
    """
    messages: list[ChannelMessage] = []
    stats: list[ChannelStats] = []
    async with (
        httpx.AsyncClient(timeout=PAGE_TIMEOUT_SEC, transport=transport) as page_client,
        httpx.AsyncClient(timeout=LINK_TIMEOUT_SEC, transport=transport) as link_client,
    ):
        for i, channel in enumerate(channels):
            if i:
                await asyncio.sleep(page_delay)  # 채널이 달라도 같은 서버다
            got = await fetch_channel(
                page_client, channel.id, since=since, until=until,
                max_pages=max_pages, page_delay=page_delay,
            )
            found = got.messages + got.undated
            stats.append(ChannelStats(
                channel=channel, pages=got.pages, messages=len(got.messages),
                undated=len(got.undated), with_links=sum(bool(m.links) for m in found),
                hidden=sum(len(m.hidden_links) for m in found), error=got.error,
            ))
            logger.info("%s: 페이지 %d, 메시지 %d건%s", channel.id, got.pages, len(got.messages),
                        f" (실패: {got.error})" if got.error else "")
            messages += found

        if open_links:
            await _attach_link_bodies(messages, stats, now=now, per_message=per_message,
                                      client=link_client)

    messages.sort(key=lambda m: (m.posted_at is None, m.posted_at or _NO_TIME, m.channel))
    return messages, stats


def write_jsonl(messages: list[ChannelMessage], out_dir: Path, collected_at: datetime) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"messages-{collected_at:%Y%m%d-%H%M%S}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for message in messages:
            f.write(message.model_dump_json() + "\n")
    return path


def summary_lines(messages: list[ChannelMessage], stats: list[ChannelStats]) -> list[str]:
    lines = []
    for s in stats:
        head = f"[{s.channel.id}] {s.channel.affiliation} · 페이지 {s.pages} · 메시지 {s.messages}건"
        if s.undated:
            head += f" (게시 시각 못 읽음 {s.undated}건)"
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
    """--show-links. 메시지 앞부분과 연 기사를 나란히 둔다. 엉뚱한 기사가 열렸는지 눈으로 본다."""
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
                   help=f"며칠 전 0시부터 모을지 (기본 {DEFAULT_DAYS})")
    p.add_argument("--channel", action="append",
                   help="채널 아이디. 여러 번 줄 수 있다. 기본은 목록 전부")
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                   help=f"채널당 최대 페이지 (기본 {DEFAULT_MAX_PAGES})")
    p.add_argument("--links-per-message", type=int, default=DEFAULT_LINKS_PER_MESSAGE,
                   help=f"메시지 하나에서 열 링크 수 (기본 {DEFAULT_LINKS_PER_MESSAGE}, 0 이면 전부)")
    p.add_argument("--no-links", action="store_true", help="링크를 열지 않는다")
    p.add_argument("--show-links", action="store_true", help="연 링크를 메시지와 나란히 보여준다")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="결과를 쓸 폴더")
    args = p.parse_args()
    if args.days < 0 or args.max_pages < 1:
        p.error("--days 는 0 이상, --max-pages 는 1 이상이어야 한다")
    try:
        channels = select_channels(args.channel)
    except ValueError as exc:
        p.error(str(exc))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # httpx 는 INFO 에서 요청마다 한 줄을 찍는다. 링크 수십 개면 요약이 묻힌다.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    now = datetime.now(KST)
    since = (now - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"수집 구간: {since:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} (KST) · 채널 {len(channels)}개")
    messages, stats = asyncio.run(collect(
        channels, since=since, until=now, now=now, max_pages=args.max_pages,
        open_links=not args.no_links, per_message=args.links_per_message,
    ))
    path = write_jsonl(messages, args.out, now)

    print("\n".join(summary_lines(messages, stats)))
    if args.show_links:
        print("\n".join(link_lines(messages)))
    print(f"\n저장: {path} ({len(messages)}건)")

    failed = [s.channel.id for s in stats if s.error]
    if failed:
        p.exit(1, f"채널 수집 실패: {', '.join(failed)}. 위의 실패 사유를 확인하세요.\n")


if __name__ == "__main__":
    main()
