import httpx
import pytest
import respx

from app.services.kakao import (
    KAKAO_TOKEN_URL,
    KAKAO_USER_URL,
    KakaoAuthError,
    exchange_code_for_token,
    fetch_user_info,
)


@respx.mock
async def test_exchange_code_for_token_returns_access_token():
    respx.post(KAKAO_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "kakao-access-token"})
    )
    token = await exchange_code_for_token("dummy-code")
    assert token == "kakao-access-token"


@respx.mock
async def test_exchange_code_for_token_wraps_http_error():
    respx.post(KAKAO_TOKEN_URL).mock(return_value=httpx.Response(400))
    with pytest.raises(KakaoAuthError):
        await exchange_code_for_token("dummy-code")


@respx.mock
async def test_exchange_code_for_token_missing_access_token_raises():
    respx.post(KAKAO_TOKEN_URL).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(KakaoAuthError):
        await exchange_code_for_token("dummy-code")


@respx.mock
async def test_fetch_user_info_parses_profile():
    respx.get(KAKAO_USER_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 123456789,
                "kakao_account": {
                    "profile": {"nickname": "테스트유저"},
                },
            },
        )
    )
    info = await fetch_user_info("dummy-token")
    assert info.kakao_id == "123456789"
    assert info.nickname == "테스트유저"


@respx.mock
async def test_fetch_user_info_wraps_http_error():
    respx.get(KAKAO_USER_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(KakaoAuthError):
        await fetch_user_info("dummy-token")


@respx.mock
async def test_exchange_code_for_token_error_includes_kakao_error_code():
    respx.post(KAKAO_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "authorization code not found for code=dummy-code",
                "error_code": "KOE303",
            },
        )
    )
    with pytest.raises(KakaoAuthError) as exc_info:
        await exchange_code_for_token("dummy-code")
    assert str(exc_info.value) == "token exchange failed: HTTP 400 KOE303"
    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


@respx.mock
async def test_exchange_code_for_token_error_without_json_keeps_message():
    respx.post(KAKAO_TOKEN_URL).mock(return_value=httpx.Response(400, text="Bad Request"))
    with pytest.raises(KakaoAuthError) as exc_info:
        await exchange_code_for_token("dummy-code")
    assert str(exc_info.value) == "token exchange failed: HTTP 400"


@respx.mock
async def test_fetch_user_info_error_includes_kakao_error_code():
    respx.get(KAKAO_USER_URL).mock(
        return_value=httpx.Response(401, json={"msg": "this access token does not exist", "code": -401})
    )
    with pytest.raises(KakaoAuthError) as exc_info:
        await fetch_user_info("dummy-token")
    # 사용자 정보 API 는 error_code 대신 code 를 준다. 없으면 기존 메시지 그대로
    assert str(exc_info.value) == "user info fetch failed: HTTP 401"
