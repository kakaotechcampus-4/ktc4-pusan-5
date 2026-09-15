import httpx
import respx
from httpx import ASGITransport
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.models import User
from app.services.kakao import KAKAO_TOKEN_URL, KAKAO_USER_URL

_KAKAO_ID = "test-router-kakao-id"
_KAKAO_USER_JSON = {
    "id": _KAKAO_ID,
    "kakao_account": {
        "email": "router-test@example.com",
        "profile": {"nickname": "라우터테스트"},
    },
}


async def _cleanup() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.kakao_id == _KAKAO_ID))
        await session.commit()


@respx.mock
async def test_kakao_login_creates_user_and_sets_cookie():
    respx.post(KAKAO_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "kakao-access-token"})
    )
    respx.get(KAKAO_USER_URL).mock(return_value=httpx.Response(200, json=_KAKAO_USER_JSON))

    transport = ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login_resp = await client.post("/api/auth/kakao", json={"code": "dummy-code"})
            assert login_resp.status_code == 200
            body = login_resp.json()
            assert body["nickname"] == "라우터테스트"
            assert body["email"] == "router-test@example.com"
            assert "accessToken" not in body  # 토큰은 쿠키로만, 응답 바디엔 없다
            assert "access_token" in login_resp.cookies

            me_resp = await client.get("/api/auth/me")
            assert me_resp.status_code == 200
            assert me_resp.json()["nickname"] == "라우터테스트"

            logout_resp = await client.post("/api/auth/logout")
            assert logout_resp.status_code == 200

            me_after_logout = await client.get("/api/auth/me")
            assert me_after_logout.status_code == 401
    finally:
        await _cleanup()


@respx.mock
async def test_kakao_login_fails_with_kakao_auth_failed_on_kakao_error():
    respx.post(KAKAO_TOKEN_URL).mock(return_value=httpx.Response(400))

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/kakao", json={"code": "dummy-code"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "KAKAO_AUTH_FAILED"


@respx.mock
async def test_kakao_login_fails_when_email_missing():
    respx.post(KAKAO_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "kakao-access-token"})
    )
    respx.get(KAKAO_USER_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": _KAKAO_ID,
                "kakao_account": {"profile": {"nickname": "라우터테스트"}},
            },
        )
    )

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/kakao", json={"code": "dummy-code"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "KAKAO_EMAIL_REQUIRED"
