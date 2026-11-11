"""Sentry 스크러버·보고 규칙 테스트. 네트워크·DB 없이 돈다."""

import json

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core import monitoring
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models import User
from app.repositories.user import get_or_create_user

FAKE_CLIENT_SECRET = "FAKE_CLIENT_SECRET_123"
FAKE_ACCESS_TOKEN = "FAKE_ACCESS_TOKEN_456"
FAKE_CODE = "FAKE_KAKAO_CODE_789"
FAKE_KIS_APP_KEY = "FAKE_KIS_APP_KEY_000"


def _fake_event(**overrides) -> dict:
    """실제 Sentry 이벤트 모양(직렬화 후). frame 변수는 repr 문자열로 들어온다."""
    event = {
        "level": "error",
        "exception": {
            "values": [
                {
                    "type": "KakaoAuthError",
                    "value": "token exchange failed: HTTP 400 KOE320",
                    "stacktrace": {
                        "frames": [
                            {
                                "module": "app.services.kakao",
                                "function": "exchange_code_for_token",
                                "context_line": '        data["client_secret"] = settings.kakao_client_secret',
                                "vars": {
                                    "code": f"'{FAKE_CODE}'",
                                    "data": {
                                        "grant_type": "'authorization_code'",
                                        "code": f"'{FAKE_CODE}'",
                                        "client_secret": f"'{FAKE_CLIENT_SECRET}'",
                                    },
                                    "access_token": f"'{FAKE_ACCESS_TOKEN}'",
                                    "kis_app_key": f"'{FAKE_KIS_APP_KEY}'",
                                    "stock_code": "'005930'",
                                    "user_id": "42",
                                    "status_code": "400",
                                    "empty": "",
                                    "nothing": None,
                                },
                            }
                        ]
                    },
                }
            ]
        },
        "request": {
            "url": "http://testserver/api/auth/kakao",
            "data": {"code": FAKE_CODE, "stock_code": "005930"},
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "httplib",
                    "message": f"POST /oauth/token access_token={FAKE_ACCESS_TOKEN}",
                    "data": {"status_code": 400, "url": "https://kauth.kakao.com/oauth/token"},
                }
            ]
        },
    }
    event.update(overrides)
    return event


def _frame_vars(event: dict) -> dict:
    return event["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]


# ── 규칙 ① 이름 규칙 ─────────────────────────────────────


def test_sensitive_names_are_masked_and_values_gone():
    result = monitoring.scrub_event(_fake_event(), {})
    dumped = json.dumps(result, ensure_ascii=False)

    for fake in (FAKE_CLIENT_SECRET, FAKE_ACCESS_TOKEN, FAKE_CODE, FAKE_KIS_APP_KEY):
        assert fake not in dumped

    frame_vars = _frame_vars(result)
    # repr 따옴표는 길이에서 뺀다
    assert frame_vars["code"] == f"[가림 str {len(FAKE_CODE)}자]"
    assert frame_vars["data"]["client_secret"] == f"[가림 str {len(FAKE_CLIENT_SECRET)}자]"
    assert frame_vars["access_token"].startswith("[가림 str")
    assert frame_vars["kis_app_key"].startswith("[가림 str")
    assert result["request"]["data"]["code"] == f"[가림 str {len(FAKE_CODE)}자]"


def test_empty_string_is_masked_and_none_kept():
    event = {"extra": {"client_secret": "", "access_token": None}}
    result = monitoring.scrub_event(event, {})
    assert result["extra"]["client_secret"] == "[가림 str 0자]"
    assert result["extra"]["access_token"] is None


def test_non_string_values_show_only_type():
    event = {"extra": {"params": {"a": 1}, "kakao_id": 3141592653, "parameters": ("x",)}}
    result = monitoring.scrub_event(event, {})
    assert result["extra"] == {
        "params": "[가림 dict]",
        "kakao_id": "[가림 int]",
        "parameters": "[가림 tuple]",
    }


def test_harmless_names_are_kept():
    frame_vars = _frame_vars(monitoring.scrub_event(_fake_event(), {}))
    assert frame_vars["stock_code"] == "'005930'"
    assert frame_vars["user_id"] == "42"
    assert frame_vars["status_code"] == "400"
    assert frame_vars["data"]["grant_type"] == "'authorization_code'"


def test_personal_info_is_removed():
    event = {
        "extra": {"nickname": "테스트닉네임", "kakao_id": "3141592653", "email": "a@b.c"},
        "message": (
            "(sqlalchemy.dialects.postgresql.asyncpg.Error) value too long\n"
            "[SQL: INSERT INTO users (kakao_id, nickname, email) VALUES ($1, $2, $3)]\n"
            "[parameters: ('3141592653', '테스트닉네임', 'a@b.c')]\n"
            "(Background on this error at: https://sqlalche.me/e/20/dbapi)"
        ),
    }
    dumped = json.dumps(monitoring.scrub_event(event, {}), ensure_ascii=False)
    for value in ("3141592653", "테스트닉네임", "a@b.c"):
        assert value not in dumped
    assert "[parameters: [가림]]" in dumped
    assert "INSERT INTO users" in dumped  # SQL 문은 남는다


def test_truncated_sql_parameters_are_masked_to_the_end():
    # 길이 제한으로 잘려 닫는 괄호가 없는 경우
    message = "[SQL: SELECT 1]\n[parameters: ('3141592653', '테스트닉"
    result = monitoring.scrub_event({"message": message}, {})
    assert "3141592653" not in result["message"]


# ── 규칙 ② 문자열 규칙 ───────────────────────────────────


def test_url_password_is_masked():
    event = {"extra": {"url": "postgresql+asyncpg://basis:pw123@db:5432/basis"}}
    result = monitoring.scrub_event(event, {})
    assert result["extra"]["url"] == "postgresql+asyncpg://basis:[가림]@db:5432/basis"


def test_settings_repr_is_cleaned():
    jwt = "j" * 40
    text = (
        f"Settings(kis_app_secret='s3cr3t', jwt_secret_key='{jwt}', app_name='BASIS API', "
        "database_url='postgresql+asyncpg://basis:pw123@db:5432/basis')"
    )
    result = monitoring.scrub_event({"extra": {"settings": text}}, {})["extra"]["settings"]
    assert "s3cr3t" not in result
    assert jwt not in result
    assert "pw123" not in result
    assert "kis_app_secret='[가림 str 6자]'" in result
    assert "jwt_secret_key='[가림 str 40자]'" in result
    assert "app_name='BASIS API'" in result


def test_query_and_path_keys_are_masked():
    event = {
        "breadcrumbs": {
            "values": [
                {"data": {"url": "https://opendart.fss.or.kr/api/list.json?crtfc_key=abc123&x=1"}},
                {"data": {"url": "https://ecos.bok.or.kr/api/StatisticSearch/ECOSKEY123/json/kr/1/10"}},
            ]
        }
    }
    values = monitoring.scrub_event(event, {})["breadcrumbs"]["values"]
    assert values[0]["data"]["url"].endswith("?crtfc_key=[가림 str 6자]&x=1")
    assert "ECOSKEY123" not in values[1]["data"]["url"]
    assert "/StatisticSearch/[가림]/json/" in values[1]["data"]["url"]


def test_message_pairs_and_bearer_are_masked():
    event = _fake_event()
    event["extra"] = {"headers": "{'Authorization': 'Bearer FAKE_BEARER_999'}"}
    result = monitoring.scrub_event(event, {})
    dumped = json.dumps(result, ensure_ascii=False)
    assert FAKE_ACCESS_TOKEN not in dumped
    assert "FAKE_BEARER_999" not in dumped
    # 카카오 오류 코드는 남아야 원인을 본다
    assert result["exception"]["values"][0]["value"] == "token exchange failed: HTTP 400 KOE320"


def test_scrub_failure_drops_event(monkeypatch):
    def broken(value, key=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(monitoring, "_scrub", broken)
    assert monitoring.scrub_event(_fake_event(), {}) is None


# ── 규칙 ③ app 밖 frame 변수 ─────────────────────────────


def _frame(module, **vars_):
    frame = {"function": "f", "context_line": "    run(args)", "vars": vars_}
    if module is not None:
        frame["module"] = module
    return frame


def test_only_app_frames_keep_var_values():
    event = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            _frame("app.repositories.user", stock_code="'005930'", nickname="'닉'"),
                            _frame(
                                "sqlalchemy.engine.base",
                                effective_parameters={"kakao_id_1": "'3141592653'"},
                                statement="'INSERT INTO users'",
                                rows="3",
                                nothing=None,
                                session="[Filtered]",
                            ),
                            # asyncpg frame 에 in_app=True 가 붙어도 module 로만 판단한다
                            {**_frame("asyncpg.prepared_stmt", args="('3141592653',)"), "in_app": True},
                            _frame(None, user_id="42"),
                            _frame("application.x", user_id="42"),  # app 으로 시작만 하는 다른 패키지
                        ]
                    }
                }
            ]
        },
        "threads": {"values": [{"stacktrace": {"frames": [_frame("__main__", user_id="42")]}}]},
    }
    result = monitoring.scrub_event(event, {})
    frames = result["exception"]["values"][0]["stacktrace"]["frames"]

    assert frames[0]["vars"] == {"stock_code": "'005930'", "nickname": "[가림 str 1자]"}
    assert frames[1]["vars"] == {
        "effective_parameters": "[가림 dict]",
        "statement": "[가림 str 17자]",
        "rows": "[가림 str 1자]",
        "nothing": None,
        "session": "[Filtered]",
    }
    assert frames[2]["vars"] == {"args": "[가림 str 15자]"}
    assert frames[3]["vars"] == {"user_id": "[가림 str 2자]"}
    assert frames[4]["vars"] == {"user_id": "[가림 str 2자]"}
    thread_frame = result["threads"]["values"][0]["stacktrace"]["frames"][0]
    assert thread_frame["vars"] == {"user_id": "[가림 str 2자]"}
    # 변수 말고 다른 frame 정보는 그대로 둔다
    assert frames[1]["module"] == "sqlalchemy.engine.base"
    assert frames[1]["context_line"] == "    run(args)"
    assert "3141592653" not in json.dumps(result, ensure_ascii=False)


# ── report() ───────────────────────────────────────────


@pytest.fixture
def captured(monkeypatch) -> list[BaseException]:
    calls: list[BaseException] = []
    monkeypatch.setattr(monitoring.sentry_sdk, "capture_exception", calls.append)
    return calls


def test_report_sends_kakao_auth_failed(captured):
    exc = AppError("KAKAO_AUTH_FAILED", "카카오 로그인에 실패했습니다", status_code=401)
    monitoring.report(exc)
    assert captured == [exc]


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("UNAUTHORIZED", 401),
        ("NOT_FOUND", 404),
        # 5xx 는 Sentry FastAPI 연동이 직접 보낸다. report() 가 또 보내면 두 번 잡힌다.
        ("SOMETHING_BROKE", 500),
    ],
)
def test_report_skips_other_codes(captured, code, status_code):
    monitoring.report(AppError(code, "x", status_code=status_code))
    assert captured == []


# ── init() ─────────────────────────────────────────────


def test_tests_never_use_real_dsn():
    # conftest.py 가 SENTRY_DSN 을 비운다. .env 에 진짜 DSN 이 있어도 테스트는 보내지 않는다.
    assert settings.sentry_dsn == ""


def test_init_without_dsn_does_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(monitoring.settings, "sentry_dsn", "")
    monkeypatch.setattr(monitoring.sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monitoring.init()
    assert calls == []


# ── 실제 SDK 파이프라인 (가짜 전송) ───────────────────────


class _MemoryTransport(Transport):
    """네트워크 대신 메모리에 담는다."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope):
        self.events.extend(item.payload.json for item in envelope.items if item.type == "event")


@pytest.fixture
def memory_sentry(monkeypatch):
    """monitoring.init() 을 실제 옵션 그대로 돌리되 전송만 메모리로 바꾼다."""
    transport = _MemoryTransport()
    real_init = sentry_sdk.init

    def init_with_memory_transport(**kwargs):
        # 자동 연동은 끈다(다른 테스트의 FastAPI·httpx 를 패치하지 않게).
        return real_init(
            **kwargs, transport=transport, default_integrations=False,
            auto_enabling_integrations=False,
        )

    monkeypatch.setattr(monitoring.settings, "sentry_dsn", "http://public@example.invalid/1")
    monkeypatch.setattr(monitoring.sentry_sdk, "init", init_with_memory_transport)
    monitoring.init()
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def _login_with_secrets():
    client_secret = FAKE_CLIENT_SECRET  # noqa: F841 — frame 변수로 실리게 둔다
    data = {"code": FAKE_CODE, "access_token": FAKE_ACCESS_TOKEN}  # noqa: F841
    raise RuntimeError(f"login failed access_token={FAKE_ACCESS_TOKEN}")


@pytest.mark.filterwarnings("ignore:The send_default_pii option is deprecated")
def test_real_pipeline_sends_no_secret(memory_sentry):
    try:
        _login_with_secrets()
    except RuntimeError as e:
        sentry_sdk.capture_exception(e)
    sentry_sdk.flush()

    assert len(memory_sentry.events) == 1
    dumped = json.dumps(memory_sentry.events, ensure_ascii=False)
    for fake in (FAKE_CLIENT_SECRET, FAKE_ACCESS_TOKEN, FAKE_CODE):
        assert fake not in dumped
    assert "[가림 str" in dumped


_DB_KAKAO_ID = "3141592653"
_DB_NICKNAME = "테스트닉네임" + "가" * 120  # users.nickname 은 VARCHAR(100). 저장에서 실제 DB 오류가 난다


def _frames(event: dict) -> list[dict]:
    return [
        frame
        for value in event["exception"]["values"]
        for frame in (value.get("stacktrace") or {}).get("frames", [])
    ]


@pytest.mark.filterwarnings("ignore:The send_default_pii option is deprecated")
async def test_real_db_error_sends_no_personal_info(memory_sentry):
    # 로컬 Postgres 필요. 실패한 INSERT 라 남는 행은 없고, 세션도 되돌린다.
    async with SessionLocal() as session:
        try:
            with pytest.raises(DBAPIError) as exc_info:
                await get_or_create_user(session, kakao_id=_DB_KAKAO_ID, nickname=_DB_NICKNAME)
            sentry_sdk.capture_exception(exc_info.value)
        finally:
            await session.rollback()
        left = await session.scalar(select(User).where(User.kakao_id == _DB_KAKAO_ID))
        assert left is None
    sentry_sdk.flush()

    assert len(memory_sentry.events) == 1
    event = memory_sentry.events[0]
    dumped = json.dumps(event, ensure_ascii=False)
    assert _DB_KAKAO_ID not in dumped
    assert "테스트닉네임" not in dumped

    frames = _frames(event)
    repo_frame = next(f for f in frames if f.get("module") == "app.repositories.user")
    assert repo_frame["vars"]["nickname"] == f"[가림 str {len(_DB_NICKNAME)}자]"  # 126자

    library_frames = [f for f in frames if (f.get("module") or "").startswith("sqlalchemy.")]
    assert library_frames
    for frame in library_frames:
        for value in (frame.get("vars") or {}).values():
            assert value is None or value == "[Filtered]" or value.startswith("[가림")
