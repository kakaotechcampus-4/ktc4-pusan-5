"""뉴스 링크 본문 수집.

    from app.services.news_link import fetch_link_bodies

    bodies = await fetch_link_bodies(urls)      # 텔레그램 메시지에 적힌 주소들

텔레그램 채널 수집은 여기 없다. 이 패키지는 **주소 목록을 받아 본문 앞부분을
돌려주는 일**만 한다. 공개 채널은 services/telegram_web 이 읽고, 둘을 잇는 것은
collectors/news_channels.py 다.
"""

from app.services.news_link.fetch import fetch_link, fetch_link_bodies, is_fetchable
from app.services.news_link.schema import LinkBody, LinkStatus

__all__ = ["LinkBody", "LinkStatus", "fetch_link", "fetch_link_bodies", "is_fetchable"]
