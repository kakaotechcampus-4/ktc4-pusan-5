"""본문을 못 얻은 사유(news.body_error)를 종류로 나눈다. 재시도할지 여기서 정한다.

body_status 는 ok·failed·purged 만 둔다. 실패의 종류는 body_error 에서 읽는다. 네이버 경로
(services/news/content.py)와 텔레그램 링크 경로(collectors/news_channels.py)가 사유를 적는
말은 다르지만, 판별은 이 함수 하나로 한다.

    permanent     다시 열어도 같은 결과다. 재시도하지 않는다
                  4xx(408·425·429 제외), HTML 아님, 크기 초과, 내부 주소, 잘못된 주소
    rate_limited  429. 요청을 너무 많이 보냈다는 응답이라 일시 실패와 따로 센다. 대기 후 재시도한다
    transient     5xx, 408·425, 타임아웃·연결 실패. 재시도한다
    extract       페이지는 받았는데 본문을 못 뽑았다. 봇 확인 페이지가 섞이므로 재시도한다.
                  다만 JS 렌더링처럼 구조적으로 못 읽는 사이트도 섞여 있어 대기 후 재시도하고,
                  3번 실패하면 포기한다
    unknown       사유가 없거나(이관 전 행 unrecorded) 처음 보는 사유. extract 처럼 다룬다

재시도 횟수는 news.body_failures(본문을 열었다가 실패한 횟수)로 센다.

HTTP 오류는 `http_error: 404` 로 적는다. 예전 네이버 행의 `http_404` 도 같은 뜻으로 읽는다.

DART 공시 목록 호출(services/dart/client.py)도 같은 형식·같은 종류를 쓴다. DART 는 HTTP 200
안에 자기 상태 코드를 주므로 `dart_status: 020` 으로 적고 아래 표로 가른다. 대기는 기사 본문
요청(news_link/fetch.py 의 open_with_backoff, 아래 retry_due)에만 있다. DART·API 호출에는
재시도·대기가 아직 없어, 종류는 다시 돌려도 되는지 판단하는 데만 쓴다.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

FailureKind = Literal["permanent", "rate_limited", "transient", "extract", "unknown"]

# 실행 안의 재시도(news_link/fetch.py)를 다 쓴 429는 다음 실행에서도 바로 재요청하지 않는다.
# 기존 수집 시각을 사용하므로 스키마 변경은 없다. 10분은 실행 안 대기의 상한(1분)보다 길게 쉬려고
# 잡은 값이고 실측 근거는 없다. 수집 주기와 실제 429 기록이 쌓이면 다시 정한다.
RATE_LIMIT_COOLDOWN = timedelta(minutes=10)

# 본문 추출 실패(extract)와 알 수 없는 실패(unknown)는 다음 실행에서도 바로 재요청하지 않고,
# 정해진 횟수를 실패하면 더 열지 않는다. 일시 실패(transient)와 달리 같은 추출기로 다시 열어도
# 같은 결과일 때가 많다(JS 렌더링 사이트 등). 수집 주기마다 같은 주소를 반복해 요청하지 않으려는
# 규칙이다. 둘 다 실측 근거는 없다.
#   30분  봇 확인 페이지가 풀릴 여지를 두면서, 장중에 실패한 기사를 그날 기준 시각(장 마감)
#         전에 한 번 더 열 수 있는 길이. 기준 시각 뒤에 받은 본문은 그날 보고서에 쓰지 않는다
#         (repositories/source_card/read_model.py hide_after_cutoff)
#   3번   처음 실패 뒤 1시간 남짓 안에 두 번 더 열어 보고 그만둔다
# 일시 실패와 429는 다시 열면 될 가능성이 높아 횟수로 포기하지 않는다. 발행·게시 24시간이 지나면
# 다시 열지 않는 규칙(collectors/news.py retry_failed, collectors/news_channels.py)만 받는다.
EXTRACT_COOLDOWN = timedelta(minutes=30)
MAX_EXTRACT_FAILURES = 3
_COOLDOWNS: dict[str, timedelta] = {
    "rate_limited": RATE_LIMIT_COOLDOWN,
    "extract": EXTRACT_COOLDOWN,
    "unknown": EXTRACT_COOLDOWN,
}
_LIMITED_KINDS = frozenset({"extract", "unknown"})

# 4xx 중 다시 요청하면 될 수 있는 것. 408 요청 시간 초과, 425 너무 이른 요청. 429 는 따로 본다.
_RETRYABLE_4XX = frozenset({408, 425})
_PERMANENT = frozenset({"not_html", "pdf", "too_large", "blocked", "blocked_address"})
_TRANSIENT = frozenset({"request_failed", "error"})
# ok 는 텔레그램 경로에서 발췌는 있는데 본문 전체가 넘어오지 않은 경우다.
_EXTRACT = frozenset({"extract_failed", "extract_empty", "clean_empty", "no_body", "ok"})
_LEGACY_HTTP = re.compile(r"http_(\d{3})")

# DART 상태 코드(opendart 개발가이드). 013(조회된 데이터 없음)은 실패가 아니라 빈 결과라 없다.
#   010·011·901 키 문제, 012 접근할 수 없는 IP, 014 파일 없음, 021 조회 회사 수 초과,
#   100·101 요청 값·접근 방식 오류. 900(정의되지 않은 오류)은 알 수 없어 unknown 으로 둔다.
_DART_PERMANENT = frozenset({"010", "011", "012", "014", "021", "100", "101", "901"})
_DART_RATE_LIMITED = "020"  # 요청 제한 초과. 사실상 429 다
_DART_TRANSIENT = frozenset({"800"})  # 시스템 점검


def http_error(status_code: int) -> str:
    """HTTP 오류의 body_error. 두 경로가 같은 형식을 쓴다."""
    return f"http_error: {status_code}"


def dart_status(code: str) -> str:
    """DART 가 정상(000)·빈 결과(013)가 아닌 상태 코드를 줬을 때의 실패 사유."""
    return f"dart_status: {code}"


def dart_failure_kind(code: str) -> FailureKind:
    if code in _DART_PERMANENT:
        return "permanent"
    if code == _DART_RATE_LIMITED:
        return "rate_limited"
    if code in _DART_TRANSIENT:
        return "transient"
    return "unknown"


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
    if head == "dart_status":
        # 뒤에 DART 가 준 안내 문구가 붙을 수 있다: "dart_status: 020 (요청 제한을 초과하였습니다.)"
        return dart_failure_kind(detail.split(" ", 1)[0])
    if head in _PERMANENT or (head == "request_failed" and detail == "invalid_address"):
        return "permanent"
    if head in _TRANSIENT:
        return "transient"
    if head in _EXTRACT:
        return "extract"
    return "unknown"


def is_retryable(body_error: str | None, failures: int = 0) -> bool:
    """다시 열어 볼 만한 실패인가. 영구 실패와, 추출 실패를 정해진 횟수만큼 한 기사를 뺀다.

    failures 는 news.body_failures. 모르면 0 으로 두어 횟수로는 포기하지 않는다.
    """
    kind = failure_kind(body_error)
    if kind == "permanent":
        return False
    return not (kind in _LIMITED_KINDS and failures >= MAX_EXTRACT_FAILURES)


def retry_due(
    body_error: str | None, fetched_at: datetime | None, *, failures: int = 0,
    now: datetime | None = None,
) -> bool:
    """재시도 가능한 실패 중 지금 요청할 것. 시각 없는 기존 행은 한 번 더 확인한다.

    마지막 시도(fetched_at)에서 429는 최소 10분, 추출 실패·알 수 없는 실패는 최소 30분을
    기다린다. 추출 실패·알 수 없는 실패는 3번 실패했으면 더 열지 않는다. 일시 실패(transient)는
    바로 다시 연다. Retry-After 헤더를 저장하지 않는 현재 구조의 기본 대기 정책이며, 호스트
    전체의 요청량 제한을 대신하지 않는다.
    """
    if not is_retryable(body_error, failures):
        return False
    kind = failure_kind(body_error)
    cooldown = _COOLDOWNS.get(kind)
    if cooldown is not None and fetched_at is not None:
        return (now or datetime.now(UTC)) - fetched_at >= cooldown
    return True
