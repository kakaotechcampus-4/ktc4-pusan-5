"""링크 한 건을 연 결과. 출처(지금은 텔레그램, 나중에 네이버)와 무관한 공통 모델.

Pydantic 을 쓰는 이유는 여기가 **외부 경계**라서다. 남의 사이트가 주는 것을 담는
그릇이고, 응답은 예고 없이 모양이 바뀐다.
(`services/analyst/schema.py`, `backend/app/services/news/schema.py` 와 같은 자리다.)

**url 은 HttpUrl 이 아니라 str 이다.** 텔레그램 본문에 적힌 주소를 그대로 키로 써야
같은 링크를 두 번 열지 않는데, HttpUrl 은 끝의 `/` 를 붙이는 등 정규화를 해서
원문에 적힌 문자열과 달라진다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# 링크를 연 결과.
#   ok          본문을 뽑았다
#   no_body     열긴 열었는데 기사 본문을 못 찾았다 (JS 로 그리는 페이지·공시 뷰어)
#   pdf         PDF 다. 본문은 못 읽고 최종 도메인만 남는다
#   not_html    HTML 도 PDF 도 아니다 (이미지·동영상)
#   too_large   본문 상한을 넘는다
#   http_error  200 이 아니다. Reuters·Bloomberg 는 봇을 막아 401/403 을 준다
#   error       네트워크·인코딩·파싱 실패
LinkStatus = Literal["ok", "no_body", "pdf", "not_html", "too_large", "http_error", "error"]


class LinkBody(BaseModel):
    """링크 하나의 수집 결과. 실패해도 버리지 않는다 — 최종 도메인만 남아도 값이 있다."""

    url: str  # 메시지에 적혀 있던 주소. 대부분 단축 URL 이다
    final_url: str | None = None  # 리다이렉트를 따라간 최종 주소
    domain: str | None = None
    status: LinkStatus = "error"
    title: str | None = None
    # 본문의 **연속된 앞부분**. 요약이 아니다. 여기서 한 글자라도 바꿔 쓰면
    # 모델이 정직하게 인용해도 "원문에 없는 인용" 으로 잡히게 된다.
    excerpt: str | None = None
    chars: int = 0
    http_status: int | None = None  # status 가 http_error 일 때만
    content_type: str | None = None  # status 가 pdf·not_html 일 때 무엇이었는지
    error: str | None = None  # status 가 error 일 때 예외 이름과 앞부분
    # 이 링크를 연 시각. tz-aware UTC 다. **기사는 발행 뒤에도 고쳐지므로**,
    # 이 값이 있어야 나중에 "대상일 컷오프보다 늦게 연 것" 을 걸러낼 수 있다.
    fetched_at: datetime
