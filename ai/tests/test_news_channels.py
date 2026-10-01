"""채널 수집기. 어떤 링크를 열고 어떤 링크를 열지 않는지가 핵심이다.

24시간이 지난 글의 링크를 열면 그때의 기사를 읽게 되어, 보고서가 컷오프로 막아둔
사후 정보가 들어온다. 가짜 서버로 돌아서 실제 사이트에 접속하지 않는다.
"""

from datetime import UTC, datetime, timedelta, timezone

import httpx

from app.collectors.news_channels import choose_links, collect, write_jsonl
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
