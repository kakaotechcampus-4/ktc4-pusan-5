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
async def test_fetch_user_info_parses_profile_and_email():
    respx.get(KAKAO_USER_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 123456789,
                "kakao_account": {
                    "email": "user@example.com",
                    "profile": {"nickname": "테스트유저"},
                },
            },
        )
    )
    info = await fetch_user_info("dummy-token")
    assert info.kakao_id == "123456789"
    assert info.nickname == "테스트유저"
    assert info.email == "user@example.com"


@respx.mock
async def test_fetch_user_info_wraps_http_error():
    respx.get(KAKAO_USER_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(KakaoAuthError):
        await fetch_user_info("dummy-token")
