"""채널 하나의 메시지를 구간만큼 모은다. 로그인·봇 토큰 없이 t.me/s/ 공개 미리보기를 읽는다.

한 페이지에 최근 글이 20개 안팎이다. 더 과거는 `?before=<그 페이지의 가장 작은 번호>` 로
거슬러 올라가고, 구간 시작보다 오래된 글이 보이면 멈춘다.

**남의 서버다.** 페이지 사이에 쉬고, 채널당 페이지 수에 상한을 둔다.
실패해도 예외를 올리지 않는다. 채널 하나가 막혔다고 나머지 채널까지 못 모으면 안 된다.
실패는 ChannelFetch.error 에 남는다.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.services.news_link.fetch import HEADERS
from app.services.telegram_web.parse import parse_page
from app.services.telegram_web.schema import ChannelMessage

BASE_URL = "https://t.me/s/"
# 채널당 최대 페이지 수. 한 페이지에 글이 20개 안팎이라 5페이지면 최근 글 100개쯤이다.
DEFAULT_MAX_PAGES = 5
# 페이지 사이에 쉬는 시간(초). 남의 서버라 연달아 두드리지 않는다.
DEFAULT_PAGE_DELAY_SEC = 1.5
# 오류 메시지는 출력 한 줄에 들어갈 만큼만 남긴다.
ERROR_MSG_MAX_CHARS = 70


@dataclass
class ChannelFetch:
    """채널 하나를 읽은 결과. 중간에 실패해도 그때까지 모은 메시지는 들어 있다."""

    channel: str
    # 구간 안 메시지. 본문 글자나 첨부 파일 이름이 있는 것만 담는다(사진만 올린 글은 뺀다)
    messages: list[ChannelMessage] = field(default_factory=list)
    undated: list[ChannelMessage] = field(default_factory=list)  # 게시 시각을 못 읽은 것
    pages: int = 0  # 실제로 요청한 페이지 수
    # 페이지 상한(max_pages)에 닿아 since 까지 내려가지 못했다. 구간 앞부분 글이 빠졌을 수 있다
    truncated: bool = False
    error: str | None = None  # 실패 사유. 성공했으면 None


async def fetch_channel(
    client: httpx.AsyncClient,
    channel: str,
    *,
    since: datetime,
    until: datetime,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay: float = DEFAULT_PAGE_DELAY_SEC,
) -> ChannelFetch:
    """since ~ until 사이에 올라온 메시지를 모은다. 실패해도 예외를 던지지 않고 error 에 남긴다.

    since·until 은 시간대가 있는 datetime 이어야 한다. 게시 시각(KST)과 크기를 비교한다.
    """
    result = ChannelFetch(channel=channel)
    url = f"{BASE_URL}{channel}"
    seen: set[int] = set()
    collected: list[ChannelMessage] = []

    while result.pages < max_pages:
        if result.pages:
            await asyncio.sleep(page_delay)
        result.pages += 1
        try:
            response = await client.get(url, headers=HEADERS, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            result.error = f"{type(exc).__name__}: {str(exc)[:ERROR_MSG_MAX_CHARS]}"
            break

        page = parse_page(response.text, channel)
        if not page:
            # 첫 페이지부터 비었으면 미리보기가 없는 채널이거나 페이지 구조가 바뀐 것이다.
            # 뒤 페이지가 빈 것은 채널의 첫 글까지 내려갔다는 뜻이라 정상이다.
            if result.pages == 1:
                result.error = "메시지를 찾지 못함 (미리보기가 없는 채널이거나 페이지 구조가 바뀜)"
            break

        for message in page:
            # 페이지가 겹쳐 같은 글이 다시 나오면 건너뛴다.
            if message.msg_id is not None and message.msg_id in seen:
                continue
            if message.msg_id is not None:
                seen.add(message.msg_id)
            if message.text or message.attachment:  # 사진·영상만 올린 글은 읽을 게 없다
                collected.append(message)

        # 구간 시작보다 오래된 글이 이 페이지에 보이면 더 과거로 갈 필요가 없다.
        dated = [m.posted_at for m in page if m.posted_at]
        if dated and min(dated) < since:
            break
        # 다음 페이지는 이 페이지의 가장 작은 글 번호보다 앞선 글들이다.
        ids = [m.msg_id for m in page if m.msg_id is not None]
        if not ids:
            break
        url = f"{BASE_URL}{channel}?before={min(ids)}"
    else:
        # break 없이 끝났다 = 상한까지 읽고도 구간 시작보다 오래된 글을 못 만났다.
        # 다 읽은 것과 구분하지 않으면 덜 모은 걸 모른 채 넘어간다.
        result.truncated = True

    # 구간 밖의 글은 버리고, 게시 시각을 모르는 글은 따로 담는다.
    for message in collected:
        if message.posted_at is None:
            result.undated.append(message)
        elif since <= message.posted_at <= until:
            result.messages.append(message)
    return result
