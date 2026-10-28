"""본문을 못 얻은 사유(news.body_error)를 종류로 나눈다. 재시도할지 여기서 정한다.

body_status 는 ok·failed·purged 만 둔다. 실패의 종류는 body_error 에서 읽는다. 네이버 경로
(services/news/content.py)와 텔레그램 링크 경로(collectors/news_channels.py)가 사유를 적는
말은 다르지만, 판별은 이 함수 하나로 한다.

    permanent     다시 열어도 같은 결과다. 재시도하지 않는다
                  4xx(408·425·429 제외), HTML 아님, 크기 초과, 내부 주소, 잘못된 주소
    rate_limited  429. 요청을 너무 많이 보냈다는 응답이라 일시 실패와 따로 센다. 재시도한다
    transient     5xx, 408·425, 타임아웃·연결 실패. 재시도한다
    extract       페이지는 받았는데 본문을 못 뽑았다. 봇 확인 페이지가 섞이므로 재시도한다
    unknown       사유가 없거나(이관 전 행 unrecorded) 처음 보는 사유. 재시도한다

HTTP 오류는 `http_error: 404` 로 적는다. 예전 네이버 행의 `http_404` 도 같은 뜻으로 읽는다.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

FailureKind = Literal["permanent", "rate_limited", "transient", "extract", "unknown"]

# 429는 다음 실행에서도 바로 재요청하지 않는다. 기존 수집 시각을 사용하므로 스키마 변경은 없다.
RATE_LIMIT_COOLDOWN = timedelta(hours=1)

# 4xx 중 다시 요청하면 될 수 있는 것. 408 요청 시간 초과, 425 너무 이른 요청. 429 는 따로 본다.
_RETRYABLE_4XX = frozenset({408, 425})
_PERMANENT = frozenset({"not_html", "pdf", "too_large", "blocked", "blocked_address"})
_TRANSIENT = frozenset({"request_failed", "error"})
# ok 는 텔레그램 경로에서 발췌는 있는데 본문 전체가 넘어오지 않은 경우다.
_EXTRACT = frozenset({"extract_failed", "extract_empty", "clean_empty", "no_body", "ok"})
_LEGACY_HTTP = re.compile(r"http_(\d{3})")


def http_error(status_code: int) -> str:
    """HTTP 오류의 body_error. 두 경로가 같은 형식을 쓴다."""
    return f"http_error: {status_code}"


def http_failure_kind(status_code: int) -> FailureKind:
    if status_code == 429:
        return "rate_limited"
    if 400 <= status_code < 500 and status_code not in _RETRYABLE_4XX:
        return "permanent"
    return "transient"


def failure_kind(body_error: str | None) -> FailureKind:
    if not body_error:
        return "unknown"
    head, _, detail = body_error.partition(":")
    head, detail = head.strip(), detail.strip()
    legacy = _LEGACY_HTTP.fullmatch(head)
    if head == "http_error" or legacy:
        code = legacy.group(1) if legacy else detail
        return http_failure_kind(int(code)) if code.isdigit() else "unknown"
    if head in _PERMANENT or (head == "request_failed" and detail == "invalid_address"):
        return "permanent"
    if head in _TRANSIENT:
        return "transient"
    if head in _EXTRACT:
        return "extract"
    return "unknown"


def is_retryable(body_error: str | None) -> bool:
    """다시 열어 볼 만한 실패인가. 영구 실패만 뺀다."""
    return failure_kind(body_error) != "permanent"


def retry_due(
    body_error: str | None, fetched_at: datetime | None, *, now: datetime | None = None,
) -> bool:
    """재시도 가능한 실패 중 지금 요청할 것. 시각 없는 기존 행은 한 번 더 확인한다.

    429는 마지막 시도에서 최소 한 시간을 기다린다. Retry-After 헤더를 저장하지 않는
    현재 구조의 기본 대기 정책이며, 호스트 전체의 요청량 제한을 대신하지 않는다.
    """
    kind = failure_kind(body_error)
    if kind == "permanent":
        return False
    if kind == "rate_limited" and fetched_at is not None:
        return (now or datetime.now(UTC)) - fetched_at >= RATE_LIMIT_COOLDOWN
    return True
