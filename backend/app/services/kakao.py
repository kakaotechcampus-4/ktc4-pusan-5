import httpx
from pydantic import BaseModel

from app.core.config import settings

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token" # 인가 코드를 토큰으로 교환
KAKAO_USER_URL = "https://kapi.kakao.com/v2/user/me" # 토큰으로 사용자 정보 조회


class KakaoAuthError(Exception):
    """카카오 인증 실패. 원인 예외는 __cause__ 에 남는다."""


class KakaoUserInfo(BaseModel):
    kakao_id: str
    nickname: str
    email: str | None = None


async def exchange_code_for_token(code: str) -> str:
    # 인가 코드를 토큰으로 교환
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.kakao_client_id,
        "redirect_uri": settings.kakao_redirect_uri,
        "code": code,
    }
    if settings.kakao_client_secret:
        data["client_secret"] = settings.kakao_client_secret

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(KAKAO_TOKEN_URL, data=data)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise KakaoAuthError(f"token exchange failed: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise KakaoAuthError(f"token exchange failed: {type(e).__name__}") from e

    access_token = resp.json().get("access_token")
    if not access_token:
        raise KakaoAuthError("token exchange failed: no access_token in response")
    return access_token


async def fetch_user_info(access_token: str) -> KakaoUserInfo:
    # access token으로 카카오 사용자 정보를 조회
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(KAKAO_USER_URL, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise KakaoAuthError(f"user info fetch failed: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise KakaoAuthError(f"user info fetch failed: {type(e).__name__}") from e

    raw = resp.json()
    account = raw.get("kakao_account", {})
    profile = account.get("profile", {})
    return KakaoUserInfo(
        kakao_id=str(raw["id"]),
        nickname=profile.get("nickname", ""),
        email=account.get("email"),
    )
