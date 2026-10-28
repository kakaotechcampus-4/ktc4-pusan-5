"""본문 실패 사유를 종류로 나누는 규칙. 재시도 대상 선정이 이 판별 하나에 기댄다."""

import pytest

from app.services.news.failure import failure_kind, http_error, is_retryable


@pytest.mark.parametrize(("body_error", "kind"), [
    ("http_error: 404", "permanent"),
    ("http_error: 410", "permanent"),
    ("http_error: 403", "permanent"),  # 봇 차단. 다시 열어도 막힌다
    ("http_404", "permanent"),  # 예전 네이버 형식
    ("http_error: 429", "rate_limited"),
    ("http_error: 408", "transient"),
    ("http_error: 503", "transient"),
    ("http_500", "transient"),
    ("request_failed: ReadTimeout", "transient"),
    ("error: ConnectError: boom", "transient"),
    ("request_failed: invalid_address", "permanent"),
    ("blocked_address", "permanent"),
    ("not_html", "permanent"),
    ("too_large", "permanent"),
    ("extract_empty", "extract"),
    ("clean_empty", "extract"),
    ("no_body", "extract"),
    ("ok: 본문 전체(text)가 넘어오지 않음", "extract"),
    ("unrecorded", "unknown"),
    (None, "unknown"),
    ("http_error: None", "unknown"),
])
def test_failure_kind(body_error, kind):
    assert failure_kind(body_error) == kind


def test_only_permanent_failures_are_not_retried():
    assert not is_retryable("http_error: 404")
    assert is_retryable("http_error: 429")
    assert is_retryable("unrecorded")


def test_http_error_format_is_shared():
    assert http_error(404) == "http_error: 404"
