"""Sentry 에러 수집. sentry_sdk 는 이 모듈에서만 import 한다.

보내기 전에 scrub_event 가 이벤트 전체를 훑어 비밀값과 개인정보를 가린다.
"""

import logging
import re
from typing import TYPE_CHECKING, Any

import sentry_sdk

from app.core.config import settings

if TYPE_CHECKING:
    # errors.py 가 이 모듈을 import 하므로 타입 검사 때만 가져온다 (순환 import 방지)
    from app.core.errors import AppError

logger = logging.getLogger(__name__)

# 4xx 지만 Sentry 로 보내는 AppError 코드. 사용자 실수가 아니라 우리 쪽 설정·연동 문제일 수 있는 것만.
REPORT_CODES: frozenset[str] = frozenset({"KAKAO_AUTH_FAILED"})


def init() -> None:
    # DSN 이 비면 아무것도 하지 않는다. 로컬·CI·테스트에서는 이벤트가 나가지 않는다.
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        send_default_pii=False,
        traces_sample_rate=0,
        before_send=scrub_event,
    )


def report(exc: "AppError") -> None:
    # 5xx AppError 는 Sentry FastAPI 연동이 이미 보낸다(failed_request_status_codes 기본값 500~599).
    # 여기서 또 보내면 같은 예외가 두 번 잡히므로 4xx 중 REPORT_CODES 만 보낸다.
    # `raise ... from e` 로 이어진 원인 예외(KakaoAuthError 등)도 함께 실린다.
    if exc.status_code < 500 and exc.code in REPORT_CODES:
        sentry_sdk.capture_exception(exc)


# ── 스크러버 ────────────────────────────────────────────────

# 규칙 ① 이름 규칙. 대소문자 무시.
# 부분 일치: 이름에 이 단어가 들어 있으면 가린다 (sort_key 같은 무해한 이름도 가려지지만 감수한다).
_PARTIAL_NAMES = ("secret", "token", "password", "key")
# 정확히 일치: 개인정보·인가 코드·SQL 파라미터. authorization·cookie 는 헤더가 frame 변수에 중첩돼 들어올 때를 위해 더했다.
_EXACT_NAMES = frozenset(
    {"code", "nickname", "kakao_id", "email", "parameters", "params", "authorization", "cookie"}
)

_NAME_CHARS = r"[\w.-]"
_SENSITIVE_NAME = (
    rf"(?<!{_NAME_CHARS})"
    rf"(?:{_NAME_CHARS}*(?:{'|'.join(_PARTIAL_NAMES)}){_NAME_CHARS}*"
    rf"|{'|'.join(sorted(_EXACT_NAMES))})"
    rf"(?!{_NAME_CHARS})"
)

# 규칙 ② 문자열 규칙에 쓰는 패턴들
# name=value, name: value, name='value', 'name': "value" — 값 부분만 가린다.
# 앞 규칙이 이미 가린 자리([가림...])는 건너뛴다.
_PAIR_RE = re.compile(
    rf"""(?P<head>{_SENSITIVE_NAME}['"]?\s*[:=]\s*)(?!\[가림)"""
    r"""(?P<value>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|[^\s&,;)\]}'"]+)""",
    re.IGNORECASE,
)
# SQLAlchemy 오류 메시지의 [parameters: ...]. 길이 제한으로 잘려 닫는 괄호가 없으면 끝까지 가린다.
_SQL_PARAMS_RE = re.compile(r"\[parameters: (?:.*?\](?=\n|$)|.*)", re.DOTALL)
# ECOS 는 키를 URL 경로에 넣는다: /StatisticSearch/<KEY>/json/
_ECOS_KEY_RE = re.compile(r"(/StatisticSearch/)[^/\s]+(/)")
# URL 의 비밀번호: scheme://user:password@host
_URL_PASSWORD_RE = re.compile(r"([a-z][a-z0-9+.-]*://[^:/@\s]+:)[^@/\s]+(@)", re.IGNORECASE)
# Authorization 헤더 값: Bearer <토큰>
_BEARER_RE = re.compile(r"(Bearer\s+)[^\s'\",]+", re.IGNORECASE)

_NAME_RE = re.compile(_SENSITIVE_NAME, re.IGNORECASE)


def _is_sensitive_name(name: str) -> bool:
    return _NAME_RE.fullmatch(name) is not None


def _placeholder(value: Any) -> Any:
    """값 대신 모양만 남긴다. None 은 그대로 둔다."""
    if value is None:
        return None
    if isinstance(value, str):
        # frame 변수는 repr 로 직렬화돼 "'abc'" 처럼 따옴표가 붙어 온다. 따옴표는 길이에서 뺀다.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        return f"[가림 str {len(value)}자]"
    return f"[가림 {type(value).__name__}]"


def _mask_pair(match: re.Match[str]) -> str:
    value = match.group("value")
    if value[0] in "'\"":
        return f"{match.group('head')}{value[0]}{_placeholder(value)}{value[0]}"
    return f"{match.group('head')}{_placeholder(value)}"


def _scrub_text(text: str) -> str:
    """규칙 ②: 문자열 안에 섞인 비밀값을 가린다."""
    text = _SQL_PARAMS_RE.sub("[parameters: [가림]]", text)
    text = _ECOS_KEY_RE.sub(r"\1[가림]\2", text)
    text = _URL_PASSWORD_RE.sub(r"\1[가림]\2", text)
    text = _BEARER_RE.sub(r"\1[가림]", text)
    return _PAIR_RE.sub(_mask_pair, text)


def _scrub(value: Any, key: str | None = None) -> Any:
    """이벤트를 재귀로 훑는다. 규칙 ①(키 이름) → 안쪽으로 내려가며 규칙 ②(문자열)."""
    if key is not None and _is_sensitive_name(key):
        return _placeholder(value)
    if isinstance(value, dict):
        return {k: _scrub(v, k if isinstance(k, str) else None) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return _scrub_text(value)
    return value


def _is_app_frame(frame: dict[str, Any]) -> bool:
    # 우리 코드인지는 module 이름으로만 판단한다. Sentry 의 in_app 은 라이브러리 frame 에도 붙어 믿을 수 없다.
    module = frame.get("module")
    return isinstance(module, str) and (module == "app" or module.startswith("app."))


def _mask_outside_app_frames(value: Any) -> None:
    """규칙 ③: app 밖 frame(라이브러리·__main__·tests·module 없음)은 변수 값을 전부 모양만 남긴다.

    SQLAlchemy·asyncpg frame 은 args, effective_parameters 같은 이름에 DB 에 넣던 값을 그대로 들고 있다.
    이름으로 다 막을 수 없어서 우리 코드 frame 의 변수만 내용을 남긴다. 이벤트 안의 모든 frames 목록에 적용.
    """
    if isinstance(value, list):
        for item in value:
            _mask_outside_app_frames(item)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key != "frames" or not isinstance(item, list):
            _mask_outside_app_frames(item)
            continue
        for frame in item:
            vars_ = frame.get("vars") if isinstance(frame, dict) else None
            if isinstance(vars_, dict) and not _is_app_frame(frame):
                frame["vars"] = {k: _mask_whole(v) for k, v in vars_.items()}


def _mask_whole(value: Any) -> Any:
    # SDK 가 이미 가린 [Filtered] 나 앞 규칙이 가린 [가림 …] 은 그대로 둔다
    if isinstance(value, str) and (value == "[Filtered]" or value.startswith("[가림")):
        return value
    return _placeholder(value)


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """before_send 훅. SDK 기본 EventScrubber 가 먼저 돈 뒤에 한 번 더 가린다.

    스크러빙 중 오류가 나면 이벤트를 버린다(None). 덜 가린 채로 보내느니 한 건 잃는 쪽을 택한다.
    """
    try:
        scrubbed = _scrub(event)  # 규칙 ①② 를 거친 새 사본
        _mask_outside_app_frames(scrubbed)
        return scrubbed
    except Exception:  # noqa: BLE001 — 어떤 오류든 이벤트를 내보내지 않는 쪽으로 끝낸다
        # exc_info 를 남기면 그 로그가 다시 Sentry 이벤트가 되므로 경고 한 줄만 남긴다.
        logger.warning("sentry scrub failed; event dropped")
        return None
