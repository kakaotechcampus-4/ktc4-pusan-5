"""t.me/s/ 웹 미리보기 읽기. 실제 텔레그램에 접속하지 않고 같은 구조의 HTML 로 돈다.

여기서 지키려는 것은 둘이다. 본문 글자가 채널에 보이는 그대로 남는다(인용 대조),
게시 시각을 정확히 읽는다(당일 컷오프).
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services.telegram_web import CHANNELS, fetch_channel, parse_page, select_channels

KST = timezone(timedelta(hours=9))


def box(post: str, *, time: str | None = None, text: str | None = None,
        author: str | None = None, views: str | None = None, doc: str | None = None) -> str:
    """텔레그램 웹 미리보기의 메시지 한 칸과 같은 구조."""
    parts = [f'<div class="tgme_widget_message js-widget_message" data-post="{post}">']
    if author:
        parts.append(f'<span class="tgme_widget_message_from_author">{author}</span>')
    if doc:
        parts.append(f'<div class="tgme_widget_message_document_title">{doc}</div>')
    if text is not None:
        parts.append(f'<div class="tgme_widget_message_text js-message_text">{text}</div>')
    if views:
        parts.append(f'<span class="tgme_widget_message_views">{views}</span>')
    if time:
        parts.append(f'<a class="tgme_widget_message_date"><time datetime="{time}">.</time></a>')
    parts.append("</div>")
    return "".join(parts)


def page(*boxes: str) -> str:
    return "<html><body>" + "".join(boxes) + "</body></html>"


def test_message_fields_are_read_as_shown() -> None:
    html = page(box(
        "skitteam/105", time="2026-09-30T01:00:00+00:00", author="한동희", views="1.2K",
        text='[SK증권] 삼성전자가 <b>HBM</b>을 공개했다<br/>기사: '
             '<a href="https://buly.kr/abc">https://buly.kr/abc</a>',
    ))

    [message] = parse_page(html, "skitteam")

    assert message.msg_id == 105
    assert message.url == "https://t.me/skitteam/105"
    assert message.posted_at == datetime(2026, 9, 30, 10, 0, tzinfo=KST), "UTC → KST"
    assert message.author == "한동희"
    assert message.views == "1.2K"
    # 굵은 글씨 앞뒤에서 끊지 않는다. 줄은 <br> 에서만 나뉜다
    assert message.text == "[SK증권] 삼성전자가 HBM을 공개했다\n기사: https://buly.kr/abc"
    assert message.links == ["https://buly.kr/abc"]


def test_channel_promotion_and_repeats_are_not_links() -> None:
    html = page(box("skitteam/1", time="2026-09-30T01:00:00+00:00", text=(
        '<a href="https://buly.kr/a">기사</a> <a href="https://buly.kr/a">같은 기사</a>'
        '<br/>채널: <a href="https://t.me/skitteam">https://t.me/skitteam</a>'
        ' <a href="tg://resolve?domain=x">앱 링크</a>'
        ' <a href="https://n.news.naver.com/article/1">네이버</a>'
    )))

    [message] = parse_page(html, "skitteam")

    assert message.links == ["https://buly.kr/a", "https://n.news.naver.com/article/1"]


def test_shown_address_wins_when_the_link_behind_it_is_stale() -> None:
    """작성자가 이전 글의 링크 서식을 복사하면 화면의 주소와 실제 링크가 다르다.

    merITz_tech 18814(2026-09-30)의 실제 모양이다. 보이는 주소는 인베스트조선의 두산 기사,
    링크는 앞 글의 대만 PCB 기사였다.
    """
    html = page(box("merITz_tech/18814", time="2026-09-30T05:07:33+00:00", text=(
        "▶ 두산 美자회사 '하이엑시엄' 나스닥 IPO 착수<br/><br/>"
        '<a href="https://buly.kr/8eoJN7z">https://buly.kr/AF38fqf</a> (인베스트조선)'
    )))

    [message] = parse_page(html, "merITz_tech")

    assert message.links == ["https://buly.kr/AF38fqf"]
    assert message.hidden_links == ["https://buly.kr/8eoJN7z"], "버리지 않고 남긴다"


def test_links_on_words_or_cut_addresses_are_not_mismatches() -> None:
    html = page(box("ch/1", time="2026-09-30T01:00:00+00:00", text=(
        '<a href="https://bbn.kiwoom.com/rfCI5698">리포트 보기</a> '
        '<a href="http://PLTR.US/">http://PLTR.US</a> '  # 끝의 / 만 다르다
        '<a href="https://example.com/a/very/long/path">https://example.com/a/very…</a>'
    )))

    [message] = parse_page(html, "ch")

    assert message.links == [
        "https://bbn.kiwoom.com/rfCI5698",
        "http://PLTR.US/",
        "https://example.com/a/very/long/path",
    ]
    assert message.hidden_links == []


def test_messages_without_text_or_time_are_still_returned() -> None:
    """걸러내는 건 부르는 쪽 몫이다. 여기서 빼면 다음 페이지 번호가 틀어진다."""
    html = page(
        box("ch/3", time="2026-09-30T01:00:00+00:00"),  # 사진만
        box("ch/2", time="2026-09-30T01:00:00+00:00", doc="반도체_주간.pdf"),
        box("ch/1", text="시각이 없는 글"),
    )

    photo, pdf, undated = parse_page(html, "ch")

    assert photo.text == "" and photo.attachment is None
    assert pdf.attachment == "반도체_주간.pdf"
    assert undated.posted_at is None


def test_time_without_timezone_is_not_trusted() -> None:
    """시간대가 없으면 UTC 인지 KST 인지 모른다. 컷오프가 9시간 틀어질 바에는 모른다고 둔다."""
    [message] = parse_page(page(box("ch/1", time="2026-09-30T10:00:00", text="글")), "ch")
    assert message.posted_at is None


# ── 페이지 넘기기 ─────────────────────────────────────────────

SINCE = datetime(2026, 9, 29, 0, 0, tzinfo=KST)
UNTIL = datetime(2026, 9, 30, 12, 0, tzinfo=KST)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_pages_back_until_the_window_starts() -> None:
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        before = request.url.params.get("before")
        if before is None:
            return httpx.Response(200, html=page(
                box("ch/12", time="2026-09-30T00:00:00+00:00", text="오늘 글"),
                box("ch/11", time="2026-09-29T03:00:00+00:00", text="어제 글"),
            ))
        if before == "11":
            return httpx.Response(200, html=page(
                box("ch/10", time="2026-09-28T15:30:00+00:00", text="구간 시작 직후"),  # 09-29 00:30
                box("ch/9", time="2026-09-28T10:00:00+00:00", text="구간 밖"),
                box("ch/8", time="2026-09-28T09:00:00+00:00"),  # 사진만
            ))
        raise AssertionError(f"구간 밖 페이지까지 내려갔다: {request.url}")

    async with _client(handler) as client:
        got = await fetch_channel(client, "ch", since=SINCE, until=UNTIL, page_delay=0)

    assert requested == ["https://t.me/s/ch", "https://t.me/s/ch?before=11"]
    assert [m.msg_id for m in got.messages] == [12, 11, 10]
    assert got.pages == 2
    assert got.error is None


async def test_textless_messages_are_dropped_but_paging_goes_on() -> None:
    """최근 글이 전부 사진이어도 다음 페이지로 넘어가야 한다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("before") is None:
            photo_only = box("ch/5", time="2026-09-30T01:00:00+00:00")
            return httpx.Response(200, html=page(photo_only))
        text = box("ch/4", time="2026-09-29T01:00:00+00:00", text="글")
        return httpx.Response(200, html=page(text))

    async with _client(handler) as client:
        got = await fetch_channel(client, "ch", since=SINCE, until=UNTIL, max_pages=2, page_delay=0)

    assert [m.msg_id for m in got.messages] == [4]


async def test_blocked_channel_is_recorded_not_raised() -> None:
    """채널 하나가 막혔다고 예외가 나면 나머지 채널을 못 모은다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with _client(handler) as client:
        got = await fetch_channel(client, "ch", since=SINCE, until=UNTIL, page_delay=0)

    assert got.messages == []
    assert "500" in (got.error or "")


async def test_page_without_messages_says_so() -> None:
    """첫 페이지가 비면 미리보기가 없는 채널이거나 페이지 구조가 바뀐 것이다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html><body>채널이 없습니다</body></html>")

    async with _client(handler) as client:
        got = await fetch_channel(client, "ch", since=SINCE, until=UNTIL, page_delay=0)

    assert "메시지를 찾지 못함" in (got.error or "")


# ── 채널 목록 ─────────────────────────────────────────────


def test_channel_list_starts_small_with_citable_research_channels() -> None:
    assert [c.id for c in CHANNELS] == ["skitteam", "merITz_tech", "KISGregKim"]
    assert {c.tier for c in CHANNELS} == {"A"}


def test_unknown_channel_id_stops_instead_of_collecting_nothing() -> None:
    assert select_channels(None) == CHANNELS
    assert [c.id for c in select_channels(["KISGregKim"])] == ["KISGregKim"]
    with pytest.raises(ValueError, match="skiteam"):
        select_channels(["skiteam"])
