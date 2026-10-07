"""채널 수집기. 어떤 링크를 열고 어떤 링크를 열지 않는지가 핵심이다.

24시간이 지난 글의 링크를 열면 그사이 고쳐진 기사를 읽게 되어, 보고서가 쓰면 안 되는
기준 시각(컷오프) 이후의 정보가 들어온다. 가짜 서버로 돌아서 실제 사이트에 접속하지 않는다.
"""

from datetime import UTC, datetime, timedelta, timezone

import httpx

from app.collectors.news_channels import (
    ChannelStats,
    attach_link_bodies,
    choose_links,
    collect,
    link_plan,
    message_row,
    news_row,
    write_jsonl,
)
from app.services.news_link.schema import LinkBody
from app.services.telegram_web import Channel, ChannelMessage
from tests.test_telegram_web import box, page

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=KST)

ARTICLE_HTML = """
<html><head><meta property="og:title" content="삼성전자 zHBM 공개"></head>
<body><article>
<p>(서울=연합뉴스) 이도흔 기자 = 삼성전자가 차세대 메모리 기술을 공개했다고 밝혔다.</p>
<p>회사는 내년 하반기 양산을 목표로 하고 있다고 이날 설명했다.</p>
<p>업계는 공급 확대가 가격에 영향을 줄 것으로 보고 있다고 전했다.</p>
</article></body></html>
"""


def _message(links: list[str], posted_at: datetime | None = NOW - timedelta(hours=1)):
    """링크만 바꿔 가며 쓰는 메시지. 게시 시각은 따로 주지 않으면 NOW 한 시간 전이다."""
    return ChannelMessage(channel="ch", msg_id=1, posted_at=posted_at, text="글", links=links)


def test_links_of_messages_older_than_a_day_are_not_opened() -> None:
    choice = choose_links(_message(["https://buly.kr/a"], NOW - timedelta(hours=25)), now=NOW)
    assert choice.stale
    assert choice.urls == []


def test_links_of_undated_messages_are_not_opened() -> None:
    """게시 시각을 모르면 24시간 안인지도 모른다."""
    choice = choose_links(_message(["https://buly.kr/a"], posted_at=None), now=NOW)
    assert choice.stale
    assert choice.urls == []


def test_ticker_strings_are_not_opened() -> None:
    """텔레그램은 'PLTR.US' 같은 티커도 링크로 만든다. 열면 엉뚱한 사이트가 나온다."""
    choice = choose_links(_message(["https://PLTR.US", "https://buly.kr/a"]), now=NOW)
    assert choice.urls == ["https://buly.kr/a"]
    assert choice.junk == 1


def test_links_beyond_the_per_message_cap_are_counted_not_lost_silently() -> None:
    links = [f"https://buly.kr/{i}" for i in range(5)]

    capped = choose_links(_message(links), now=NOW, per_message=3)
    assert capped.urls == links[:3]
    assert capped.skipped == 2

    everything = choose_links(_message(links), now=NOW, per_message=0)
    assert everything.urls == links
    assert everything.skipped == 0


async def test_collect_opens_only_recent_links_and_resolves_short_urls() -> None:
    opened: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "t.me":
            if request.url.params.get("before"):
                return httpx.Response(200, html=page())  # 채널의 첫 글까지 내려왔다
            return httpx.Response(200, html=page(
                box("skitteam/2", time="2026-09-30T01:00:00+00:00",  # 2시간 전
                    text='오늘 기사 <a href="https://buly.kr/new">https://buly.kr/new</a>'),
                box("skitteam/1", time="2026-09-29T02:00:00+00:00",  # 25시간 전
                    text='어제 기사 <a href="https://buly.kr/old">https://buly.kr/old</a>'),
            ))
        opened.append(str(request.url))
        if request.url.host == "buly.kr":
            return httpx.Response(302, headers={"location": "https://news.example.com/a/1"})
        return httpx.Response(200, html=ARTICLE_HTML)

    channels = (Channel("skitteam", "[ IT는 SK ]", "SK증권 리서치 IT팀", "A"),)
    messages, stats = await collect(
        channels, since=datetime(2026, 9, 29, 0, 0, tzinfo=KST), until=NOW, now=NOW,
        page_delay=0, transport=httpx.MockTransport(handler),
    )

    old, new = messages  # 게시 시각순
    assert "https://buly.kr/old" not in opened
    assert old.link_bodies == []
    [body] = new.link_bodies
    assert body.status == "ok"
    assert body.final_url == "https://news.example.com/a/1", "단축 URL 이 풀려야 출처가 보인다"
    assert body.excerpt and body.excerpt.startswith("삼성전자가 차세대 메모리 기술을")
    [stat] = stats
    assert (stat.messages, stat.with_links, stat.opened, stat.stale) == (2, 2, 1, 1)
    assert stat.error is None


async def test_no_links_option_leaves_links_unopened() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "t.me":
            raise AssertionError(f"링크를 열었다: {request.url}")
        if request.url.params.get("before"):
            return httpx.Response(200, html=page())
        return httpx.Response(200, html=page(box(
            "ch/1", time="2026-09-30T01:00:00+00:00",
            text='<a href="https://buly.kr/a">https://buly.kr/a</a>')))

    messages, _stats = await collect(
        (Channel("ch", "채널", "소속", "A"),), since=NOW - timedelta(days=1), until=NOW,
        now=NOW, page_delay=0, open_links=False, transport=httpx.MockTransport(handler),
    )

    assert messages[0].links == ["https://buly.kr/a"]
    assert messages[0].link_bodies == []


def test_jsonl_keeps_korean_and_leaves_the_whole_article_out(tmp_path) -> None:
    body = LinkBody(url="https://buly.kr/a", status="ok", excerpt="발췌",
                    sentences=["기사 전문의 첫 문장이다."], fetched_at=datetime.now(UTC))
    message = ChannelMessage(channel="skitteam", msg_id=1, text="삼성전자", link_bodies=[body])

    path = write_jsonl([message], tmp_path / "telegram", NOW)

    raw = path.read_text(encoding="utf-8")
    assert path.name == "messages-20260930-120000.jsonl"
    assert "삼성전자" in raw, "\\uXXXX 로 바뀌면 파일을 눈으로 볼 수 없다"
    assert "기사 전문" not in raw


# ── DB 에 넣을 행 ─────────────────────────────────────────────


def _opened(url: str, **values) -> LinkBody:
    return LinkBody(url=url, fetched_at=datetime(2026, 9, 30, 2, 0, tzinfo=UTC), **values)


def test_every_link_is_kept_with_the_reason_it_was_not_opened() -> None:
    """열지 않은 링크도 발견한 사실은 남긴다. 왜 안 열었는지가 상태다."""
    links = ["https://buly.kr/a", "https://PLTR.US", "https://buly.kr/b", "https://buly.kr/c"]
    recent = _message(links)
    recent.link_bodies = [_opened("https://buly.kr/a", status="ok", text="본문"),
                          _opened("https://buly.kr/b", status="http_error", http_status=403)]

    plan = link_plan(recent, now=NOW, per_message=2)
    assert [(url, status) for url, status, _body in plan] == [
        ("https://buly.kr/a", "ok"),
        ("https://PLTR.US", "not_fetchable"),
        ("https://buly.kr/b", "http_error"),
        ("https://buly.kr/c", "over_limit"),
    ]

    old = _message(links[:1], NOW - timedelta(hours=25))
    assert link_plan(old, now=NOW, per_message=2)[0][1] == "stale"
    # 열기로 골랐는데 결과가 없다: 수집 범위 때문이면 out_of_scope, --no-links 면 not_opened
    assert link_plan(_message(links[:1]), now=NOW, per_message=2)[0][1] == "out_of_scope"
    assert link_plan(_message(links[:1]), now=NOW, per_message=2,
                     unopened="not_opened")[0][1] == "not_opened"


async def test_link_budget_opens_only_that_many_addresses() -> None:
    """수집 범위의 남은 수집량만큼만 연다. 못 연 주소 수를 돌려준다."""
    opened: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        opened.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    messages = [_message([f"https://news.example.com/{i}" for i in range(3)])]
    stats = [ChannelStats(channel=Channel("ch", "채널", "소속", "A"))]
    held = await attach_link_bodies(messages, stats, now=NOW, per_message=3, max_links=1,
                                    transport=httpx.MockTransport(handler))

    assert (held, opened) == (2, ["https://news.example.com/0"])
    assert [body.url for body in messages[0].link_bodies] == ["https://news.example.com/0"]
    statuses = [status for _url, status, _body in link_plan(messages[0], now=NOW, per_message=3)]
    assert statuses == ["ok", "out_of_scope", "out_of_scope"]


def test_news_row_stores_the_whole_body_not_the_excerpt() -> None:
    body = _opened("https://buly.kr/a", final_url="https://www.News.example.com/a/1",
                   domain="www.News.example.com", status="ok", title="제목",
                   excerpt="첫 문장.", text="첫 문장. 둘째 문장.")
    row = news_row(body)
    assert row["cleaned_text"] == "첫 문장. 둘째 문장."
    assert row["published_at"] is None, "링크를 연 시각을 발행 시각으로 쓰지 않는다"
    assert row["body_fetched_at"] == body.fetched_at
    assert (row["source"], row["publisher"], row["url"]) == (
        "telegram", "news.example.com", "https://www.News.example.com/a/1")


def test_failed_article_is_kept_for_retry_but_non_articles_are_not() -> None:
    failed = news_row(_opened("https://buly.kr/a", final_url="https://reuters.com/a",
                              domain="reuters.com", status="http_error", http_status=401))
    assert (failed["body_status"], failed["body_error"], failed["cleaned_text"]) == (
        "failed", "http_error: 401", None)
    assert failed["title"] == ""

    for status in ("pdf", "not_html"):
        assert news_row(_opened("https://buly.kr/p", final_url="https://file.example.com/r.pdf",
                                status=status)) is None
    assert news_row(_opened("https://buly.kr/x", status="blocked", error="내부 주소")) is None
    assert news_row(_opened("https://buly.kr/y", status="error", error="DNS")) is None, \
        "도착한 주소를 모르면 어떤 기사인지 모른다"


def test_message_row_keeps_text_as_shown_and_unknown_time_as_none() -> None:
    message = ChannelMessage(channel="ch", msg_id=7, posted_at=None, text="  글  ",
                             attachment="r.pdf", edited=True, views="1.2K")
    row = message_row(message, channel_id=3)
    assert (row["text"], row["posted_at"], row["url"]) == ("  글  ", None, "https://t.me/ch/7")
    assert (row["attachment_name"], row["edited"], row["collected_via"]) == ("r.pdf", True, "web")
    assert row["forwarded_from"] is None, "운영자가 쓴 글이다"

    forwarded = message.model_copy(update={"forwarded_from": "다른 채널",
                                           "forwarded_from_url": "https://t.me/other/9"})
    row = message_row(forwarded, channel_id=3)
    assert (row["forwarded_from"], row["forwarded_from_url"]) == ("다른 채널", "https://t.me/other/9")
