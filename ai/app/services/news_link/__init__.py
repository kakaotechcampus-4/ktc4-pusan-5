"""뉴스 링크 본문 수집과 종목별 원인 문장 선택.

    from app.services.news_link import fetch_link_bodies, select_sentences

    bodies = await fetch_link_bodies(urls)                  # 텔레그램 메시지에 적힌 주소들
    picked = await select_sentences("삼성전자", bodies[0])  # 그 기사에서 이 종목의 원인 문장

본문 수집은 LLM 을 부르지 않고 링크당 한 번만 연다. 문장 선택은 (링크, 종목)마다
LLM 을 한 번 부른다(selection.py).

텔레그램 채널 수집(t.me/s/ 또는 Telethon)은 여기 없다. 이 패키지는 **주소 목록을
받아 본문을 돌려주고, 종목별로 원인 문장을 고르는 일**만 한다. 채널을 붙이는 쪽이
정해지면 collectors/ 에서 이걸 불러 쓰면 된다.
"""

from app.services.news_link.fetch import fetch_link, fetch_link_bodies, is_fetchable
from app.services.news_link.schema import LinkBody, LinkSelection, LinkStatus, SelectionStatus
from app.services.news_link.selection import select_sentences

__all__ = [
    "LinkBody",
    "LinkSelection",
    "LinkStatus",
    "SelectionStatus",
    "fetch_link",
    "fetch_link_bodies",
    "is_fetchable",
    "select_sentences",
]
