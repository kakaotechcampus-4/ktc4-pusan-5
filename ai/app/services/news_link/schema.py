"""링크 한 건을 연 결과와, 그 기사에서 종목별로 고른 문장. 출처(지금은 텔레그램,
나중에 네이버)와 무관한 공통 모델.

Pydantic 을 쓰는 이유는 여기가 **외부 경계**라서다. 남의 사이트가 주는 것을 담는
그릇이고, 응답은 예고 없이 모양이 바뀐다. LLM 이 돌려준 답(고른 번호)도 마찬가지다.
(`services/analyst/schema.py`, `backend/app/services/news/schema.py` 와 같은 자리다.)

**url 은 HttpUrl 이 아니라 str 이다.** 텔레그램 본문에 적힌 주소를 그대로 키로 써야
같은 링크를 두 번 열지 않는데, HttpUrl 은 끝의 `/` 를 붙이는 등 정규화를 해서
원문에 적힌 문자열과 달라진다.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# 링크를 연 결과.
#   ok          본문을 뽑았다
#   no_body     열긴 열었는데 기사 본문을 못 찾았다 (JS 로 그리는 페이지·공시 뷰어)
#   pdf         PDF 다. 본문은 못 읽고 최종 도메인만 남는다
#   not_html    HTML 도 PDF 도 아니다 (이미지·동영상)
#   too_large   본문 상한을 넘는다
#   http_error  200 이 아니다. Reuters·Bloomberg 는 봇을 막아 401/403 을 준다
#   blocked     공개 인터넷 주소가 아니라서 열지 않았다 (fetch.py 의 SSRF 방어)
#   error       네트워크·인코딩·파싱 실패
LinkStatus = Literal[
    "ok", "no_body", "pdf", "not_html", "too_large", "http_error", "blocked", "error"
]


class LinkBody(BaseModel):
    """링크 하나의 수집 결과. 실패해도 버리지 않는다 — 최종 도메인만 남아도 값이 있다."""

    url: str  # 메시지에 적혀 있던 주소. 대부분 단축 URL 이다
    final_url: str | None = None  # 리다이렉트를 따라간 최종 주소. blocked 면 비어 있다
    domain: str | None = None
    status: LinkStatus = "error"
    title: str | None = None
    # 본문의 **연속된 앞부분**. 요약이 아니다. 여기서 한 글자라도 바꿔 쓰면
    # 모델이 정직하게 인용해도 "원문에 없는 인용" 으로 잡히게 된다.
    excerpt: str | None = None
    chars: int = 0
    http_status: int | None = None  # status 가 http_error 일 때만
    content_type: str | None = None  # status 가 pdf·not_html 일 때 무엇이었는지
    # status 가 error 면 예외 이름과 앞부분, blocked 면 막힌 목적지 주소
    error: str | None = None
    # 이 링크를 연 시각. tz-aware UTC 다. **기사는 발행 뒤에도 고쳐지므로**,
    # 이 값이 있어야 나중에 "대상일 컷오프보다 늦게 연 것" 을 걸러낼 수 있다.
    fetched_at: datetime
    # 정제한 본문 **전체**를 문장으로 나눈 것. 종목별 문장 선택(selection.py)이 여기서 고른다.
    # JSON 으로 내보낼 때 뺀다(exclude). 본문 전량이 보고서 프롬프트로 새면 토큰이 몇 배가 되고
    # (sentence.py 참고), 기사 전문을 어디에 얼마나 둘지는 아직 정하지 않았다. 그래서 파일에서
    # 다시 읽은 LinkBody 는 이 값이 비어 있다.
    # repr 에서도 뺀다. 로그에 기사 전문이 찍히지 않게 하려는 것이다.
    sentences: list[str] = Field(default_factory=list, exclude=True, repr=False)
    # 정제한 본문 전체(문장으로 나누기 전 그대로). news 표의 본문(cleaned_text)으로 저장한다
    # (collectors/news_channels.py). excerpt 나 종목별로 고른 문장을 본문 자리에 넣지 않으려고
    # 따로 둔다. sentences 와 같은 이유로 직렬화·repr 에서 뺀다.
    text: str | None = Field(default=None, exclude=True, repr=False)


# 종목별 문장 선택의 결과.
#   selected  고른 문장이 있다
#   none      이 기사는 이 종목을 다루지 않는다. 발췌가 없다
#   fallback  모델 응답이 규칙을 어겼다. 앞 3문장으로 대체했다
#   error     호출이 실패했다. 앞 3문장으로 대체했다
#   no_body   고를 본문이 없다(PDF·본문 못 찾음·열기 실패). 호출하지 않았다
SelectionStatus = Literal["selected", "none", "fallback", "error", "no_body"]


class LinkSelection(BaseModel):
    """(링크, 종목) 한 쌍의 발췌. 링크 하나에 종목이 여럿이면 종목마다 하나씩 생긴다."""

    url: str
    stock: str
    status: SelectionStatus
    # 고른 문장을 번호 순서대로 이은 것. **글자는 원문 그대로**다. 떨어진 문장끼리도
    # 공백 하나로 잇는다. none·no_body 면 없고, fallback·error 면 앞 3문장이다.
    excerpt: str | None = None
    # excerpt 에 들어간 문장 번호(1부터). 코드가 앞 문장을 붙인 뒤의 값이다.
    indices: list[int] = Field(default_factory=list)
    # 모델이 고른 번호(코드가 앞 문장을 붙이기 전). indices 와 비교하면 모델이 앞 문장을
    # 얼마나 빠뜨리는지 알 수 있다.
    model_indices: list[int] = Field(default_factory=list)
    raw: str = ""  # 모델 응답 원문. fallback 이 왜 났는지 볼 때 쓴다
    error: str | None = None  # status 가 error 일 때만
    usage: dict[str, Any] = Field(default_factory=dict)  # 토큰 수·비용. complete() 가 돌려준 그대로
    prompt_sha256: str | None = None  # 어느 버전의 프롬프트로 골랐나 (news_select.md 의 sha256)
