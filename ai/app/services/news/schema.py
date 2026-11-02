"""소스에 상관없이 공통으로 쓰는 뉴스 항목 모델.

backend `services/news/schema.py` 에서 옮겨 왔다. 텔레그램 메시지 링크로 연 기사는
이 모델을 거치지 않는다 — news_link 의 LinkBody 를 collectors/news_channels.py 가
같은 news 표의 행으로 바꾼다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, HttpUrl

NewsSource = Literal["naver", "kis"]


class NewsItem(BaseModel):
    title: str
    url: HttpUrl  # 원문 URL (언론사 사이트)
    publisher: str  # 매체 식별자. 지금은 원문 도메인, 추후 매체명 매핑
    published_at: datetime  # timezone-aware
    source: NewsSource  # 어느 API에서 가져왔는지
    summary: str = ""  # 소스가 주는 요약/설명. 본문 아님
    related_codes: list[str] = []  # 관련 종목코드. KIS만 채워줌
    raw_text: str | None = None  # 원문 본문. 추출 성공 시에만
    cleaned_text: str | None = None  # 꼬리말·번역본 제거, 길이 상한 적용 (clean.py)
    body_error: str | None = None  # 본문 추출 실패 사유. 실패해도 항목은 버리지 않는다
    # 본문을 받으러 원문을 연 시각(UTC). 성공·실패 모두 채운다. 기사는 발행 뒤에도 고쳐지므로
    # 보고서 기준 시각보다 늦게 받은 본문을 걸러낼 때 쓴다. 열지 않았으면 None 이다.
    body_fetched_at: datetime | None = None
