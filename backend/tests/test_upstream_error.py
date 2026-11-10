import httpx
import pytest

from app.services.market_calendar import KST, market_close_at
from app.services.market_data import MarketDataError, classify_upstream_error

REQUEST = httpx.Request("GET", "http://upstream.test")


def _status(code):
    return httpx.HTTPStatusError(
        "boom", request=REQUEST, response=httpx.Response(code, request=REQUEST)
    )


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        # 응답이 온 경우: 상태 코드별로 코드가 갈린다.
        (_status(401), "UPSTREAM_HTTP_401"),
        (_status(429), "UPSTREAM_HTTP_429"),
        (_status(500), "UPSTREAM_HTTP_500"),
        (_status(503), "UPSTREAM_HTTP_503"),
        # 응답이 없는 경우: 시간 초과와 연결 실패는 해석 실패와 구분한다.
        (TimeoutError(), "UPSTREAM_TIMEOUT"),
        (httpx.ReadTimeout("slow", request=REQUEST), "UPSTREAM_TIMEOUT"),
        (httpx.ConnectTimeout("slow", request=REQUEST), "UPSTREAM_TIMEOUT"),
        (httpx.ConnectError("refused", request=REQUEST), "UPSTREAM_UNREACHABLE"),
        (ConnectionResetError(), "UPSTREAM_UNREACHABLE"),
        # 응답은 왔으나 해석하지 못한 경우
        (KeyError("output"), "INVALID_RESPONSE"),
        (TypeError(), "INVALID_RESPONSE"),
        (IndexError(), "INVALID_RESPONSE"),
        (ValueError("bad json"), "INVALID_RESPONSE"),
        # 이미 고정 코드가 붙은 오류는 그대로
        (MarketDataError("UPSTREAM_ERROR"), "UPSTREAM_ERROR"),
    ],
)
def test_classify_upstream_error(exc, expected):
    assert classify_upstream_error(exc) == expected


@pytest.mark.parametrize("exc", [RuntimeError("bug"), AttributeError("bug"), ZeroDivisionError()])
def test_unknown_exceptions_are_not_swallowed(exc):
    assert classify_upstream_error(exc) is None


def test_market_close_at_uses_calendar_close_time():
    from datetime import date

    close = market_close_at(date(2026, 10, 30))
    assert close.tzinfo is KST or close.utcoffset() == KST.utcoffset(None)
    assert (close.hour, close.minute) == (15, 40)


@pytest.mark.parametrize("status", [400, 403, 404, 405, 410, 422])
def test_client_errors_are_permanent(status):
    from app.core.retry_policy import is_permanent_error

    assert is_permanent_error(classify_upstream_error(_status(status)))


@pytest.mark.parametrize("status", [401, 408, 429, 500, 502, 503, 504])
def test_auth_rate_limit_and_server_errors_are_transient(status):
    from app.core.retry_policy import is_permanent_error

    assert not is_permanent_error(classify_upstream_error(_status(status)))


@pytest.mark.parametrize(
    "code", ["MISSING_KEY", "UNSUPPORTED_ENV", "UPSTREAM_ERROR"]
)
def test_config_and_business_errors_are_permanent(code):
    from app.core.retry_policy import is_permanent_error

    assert is_permanent_error(code)


@pytest.mark.parametrize(
    "code",
    [
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_UNREACHABLE",
        "UPSTREAM_AUTH",
        "UPSTREAM_RATE_LIMITED",
        "INVALID_RESPONSE",
        "AUTH_COOLDOWN",
        None,
    ],
)
def test_other_errors_stay_transient(code):
    from app.core.retry_policy import is_permanent_error

    assert not is_permanent_error(code)
