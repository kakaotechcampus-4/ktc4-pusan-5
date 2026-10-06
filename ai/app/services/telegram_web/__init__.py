"""텔레그램 공개 채널을 로그인 없이 읽는다 (t.me/s/<채널> 웹 미리보기).

    from app.services.telegram_web import CHANNELS, fetch_channel

    got = await fetch_channel(client, "skitteam", since=since, until=now)

증권사 리포트 PDF 를 받는 services/analyst/telegram.py 와 다르다. 그쪽은 로그인한 계정으로
Telethon 을 쓰고, 이쪽은 누구나 볼 수 있는 웹 미리보기만 읽는다. 계정이 없어도 돌아간다.
메시지에 걸린 뉴스 링크를 여는 일은 services/news_link 가 한다. 둘을 잇는 것은
collectors/news_channels.py 다.
"""

from app.services.telegram_web.channels import CHANNELS, Channel, select_channels
from app.services.telegram_web.fetch import ChannelFetch, fetch_channel
from app.services.telegram_web.parse import parse_page
from app.services.telegram_web.schema import ChannelMessage

__all__ = [
    "CHANNELS",
    "Channel",
    "ChannelFetch",
    "ChannelMessage",
    "fetch_channel",
    "parse_page",
    "select_channels",
]
