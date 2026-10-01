"""t.me/s/<채널> 페이지 HTML → 메시지.

텔레그램 웹 미리보기의 메시지 구조(2026-09-30 확인):

    div.tgme_widget_message[data-post="채널/번호"]
      div.tgme_widget_message_text             본문. 줄바꿈은 <br>
      time[datetime]                           게시 시각 (ISO 8601, UTC)
      span.tgme_widget_message_from_author     채널 안 서명
      span.tgme_widget_message_views           조회수
      div.tgme_widget_message_document_title   첨부 파일 이름

구조가 바뀌면 메시지가 0건이 된다. 그때는 fetch.py 가 "메시지를 찾지 못함" 을 남긴다.
"""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.telegram_web.schema import ChannelMessage

KST = timezone(timedelta(hours=9))

# 링크로 치지 않는 호스트. 채널 홍보("SK증권 리서치 IT팀 채널: https://t.me/skitteam")다.
TELEGRAM_HOSTS = ("t.me", "telegram.me", "www.t.me", "telegram.org")
# 링크 글자가 주소 그 자체인가. 말줄임(…)이 있으면 잘려서 보이는 것이라 주소로 치지 않는다.
SHOWN_URL_RE = re.compile(r"https?://[^\s…]+")


def _text(node) -> str:
    """본문 글자. <br> 만 줄바꿈으로 바꾸고, 나머지 태그는 글자만 남긴다.

    프로토타입은 태그 경계마다 줄바꿈을 넣었다(get_text("\\n")). 그러면 굵은 글씨·이모지·
    링크 앞뒤에서 문장이 끊기고("<b>HBM</b>을" → "HBM\\n을") 빈 줄이 늘어난다. skitteam
    한 페이지로 두 방식을 비교하니 19건 중 18건이 달랐다(대부분 늘어난 빈 줄).
    """
    for br in node.find_all("br"):
        br.replace_with("\n")
    return node.get_text().strip()


def _is_external(url: str) -> bool:
    return (url.startswith(("http://", "https://"))
            and urlparse(url).netloc.lower() not in TELEGRAM_HOSTS)


def _links(node) -> tuple[list[str], list[str]]:
    """(링크, 숨은 링크).

    **링크 글자가 주소인데 실제 링크(href)와 다르면 보이는 주소를 쓴다.** 작성자가 이전 글의
    링크 서식을 복사해 글자만 바꾸면, 화면에는 새 주소가 보이는데 링크는 옛 기사로 간다.
    merITz_tech 18813·18814(2026-09-30)가 "https://buly.kr/15RjeQe (Digitimes)" 처럼 서로 다른
    주소를 보여주면서 링크는 둘 다 같은 대만 기사로 걸려 있었다. 보이는 주소를 풀어 보니
    적힌 출처(Digitimes·인베스트조선)와 글 내용에 맞는 기사였다.
    쓰지 않은 href 는 숨은 링크로 따로 돌려준다. 버리면 이런 일이 있었는지조차 모른다.

    "기사" 처럼 주소가 아닌 글자에 건 링크는 href 를 그대로 쓴다.
    """
    links: list[str] = []
    hidden: list[str] = []
    for anchor in node.find_all("a", href=True):
        href = anchor["href"]
        shown = anchor.get_text().strip()
        url = href
        # 끝의 / 만 다른 것은 같은 주소다. 텔레그램이 "PLTR.US" 를 "PLTR.US/" 로 건다.
        if SHOWN_URL_RE.fullmatch(shown) and shown.rstrip("/") != href.rstrip("/"):
            url = shown
            if _is_external(href) and href not in hidden:
                hidden.append(href)
        if _is_external(url) and url not in links:
            links.append(url)
    return links, hidden


def _posted_at(box) -> datetime | None:
    """게시 시각을 KST 로. 시간대가 없는 값은 믿지 않는다 — 컷오프가 9시간 틀어진다."""
    node = box.select_one("time[datetime]")
    raw = node.get("datetime") if node else None
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)  # 3.11 부터 끝의 "Z" 도 읽는다
    except ValueError:
        return None
    return parsed.astimezone(KST) if parsed.tzinfo else None


def _msg_id(post: str) -> int | None:
    _channel, _, number = post.rpartition("/")
    return int(number) if number.isdigit() else None


def _plain(box, selector: str) -> str | None:
    node = box.select_one(selector)
    if node is None:
        return None
    return node.get_text(strip=True) or None


def parse_page(html: str, channel: str) -> list[ChannelMessage]:
    """페이지에 있는 메시지 전부. **사진만 올린 글처럼 글자가 없는 것도 돌려준다.**

    걸러내는 건 부르는 쪽 몫이다. 여기서 빼면 페이지를 넘길 때 쓰는 가장 작은 번호가
    틀어진다 — 최근 글이 전부 사진이면 다음 페이지로 못 넘어간다.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[ChannelMessage] = []
    for box in soup.select("div.tgme_widget_message"):
        msg_id = _msg_id(box.get("data-post", ""))
        text_node = box.select_one("div.tgme_widget_message_text")
        links, hidden = _links(text_node) if text_node else ([], [])
        out.append(
            ChannelMessage(
                channel=channel,
                msg_id=msg_id,
                url=f"https://t.me/{channel}/{msg_id}" if msg_id is not None else None,
                posted_at=_posted_at(box),
                author=_plain(box, "span.tgme_widget_message_from_author"),
                views=_plain(box, "span.tgme_widget_message_views"),
                links=links,
                hidden_links=hidden,
                text=_text(text_node) if text_node else "",
                attachment=_plain(box, "div.tgme_widget_message_document_title"),
            )
        )
    return out
