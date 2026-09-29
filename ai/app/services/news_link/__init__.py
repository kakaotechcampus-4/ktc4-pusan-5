"""뉴스 링크 본문 수집.

    from app.services.news_link import fetch_link_bodies

    bodies = await fetch_link_bodies(urls)      # 텔레그램 메시지에 적힌 주소들

텔레그램 채널 수집(t.me/s/ 또는 Telethon)은 여기 없다. 이 패키지는 **주소 목록을
받아 본문 앞부분을 돌려주는 일**만 한다. 채널을 붙이는 쪽이 정해지면
collectors/ 에서 이걸 불러 쓰면 된다.
"""

from app.services.news_link.fetch import fetch_link, fetch_link_bodies, is_fetchable
from app.services.news_link.schema import LinkBody, LinkStatus

__all__ = ["LinkBody", "LinkStatus", "fetch_link", "fetch_link_bodies", "is_fetchable"]
