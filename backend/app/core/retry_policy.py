"""수집 작업 재시도 정책. 어떤 오류를 몇 번까지 다시 시도할지만 정한다."""

# 다시 받아도 같은 결과일 오류. 요청이나 설정이 잘못됐거나 상대가 거절한 경우다.
# 408·429·5xx 와 401(토큰 갱신 후 성공할 수 있음)은 일시 오류라 여기에 넣지 않는다.
# INVALID_RESPONSE 는 원인이 여러 가지라 아직 일시 오류로 둔다.
PERMANENT_HTTP_STATUSES = frozenset({400, 403, 404, 405, 410, 422})
PERMANENT_ERROR_CODES = frozenset(
    {
        "MISSING_KEY",
        "UNSUPPORTED_ENV",
        "UPSTREAM_ERROR",
        *(f"UPSTREAM_HTTP_{status}" for status in PERMANENT_HTTP_STATUSES),
    }
)

# 일시 오류는 충분히 다시 시도하고, 영구 오류는 오분류를 한 번 구제할 만큼만 다시 시도한다.
MAX_ATTEMPTS = 5
PERMANENT_MAX_ATTEMPTS = 3


def is_permanent_error(code: str | None) -> bool:
    return code in PERMANENT_ERROR_CODES

