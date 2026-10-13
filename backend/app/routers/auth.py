from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.core.security import ACCESS_TOKEN_COOKIE, create_access_token
from app.models import User
from app.repositories.user import get_or_create_user
from app.schemas.auth import KakaoLoginRequest, UserResponse
from app.services.kakao import KakaoAuthError, exchange_code_for_token, fetch_user_info

router = APIRouter()

_COOKIE_MAX_AGE = settings.jwt_expire_minutes * 60

# 카카오 id와 겹치지 않는 고정 식별자(카카오 id는 숫자 문자열만 나옴)
_TEST_ACCOUNT_KAKAO_ID = "TEST_ACCOUNT"
_TEST_ACCOUNT_NICKNAME = "테스트 계정"


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        nickname=user.nickname,
    )


def _set_session_cookie(response: Response, user_id: int) -> None:
    token = create_access_token(user_id)
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.post("/kakao", response_model=UserResponse)
async def login_with_kakao(
    body: KakaoLoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    try:
        kakao_access_token = await exchange_code_for_token(body.code)
        kakao_user = await fetch_user_info(kakao_access_token)
    except KakaoAuthError as e:
        raise AppError("KAKAO_AUTH_FAILED", "카카오 로그인에 실패했습니다", status_code=401) from e

    user = await get_or_create_user(
        session,
        kakao_id=kakao_user.kakao_id,
        nickname=kakao_user.nickname,
    )
    await session.commit()

    _set_session_cookie(response, user.id)
    return _to_response(user)


@router.post("/test-login", response_model=UserResponse)
async def login_as_test_account(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    # 로컬 개발 전용. 꺼져 있으면 엔드포인트 자체가 없는 것처럼 404로 응답한다
    if not settings.enable_test_login:
        raise AppError("NOT_FOUND", "요청한 리소스를 찾을 수 없습니다", status_code=404)

    user = await get_or_create_user(
        session,
        kakao_id=_TEST_ACCOUNT_KAKAO_ID,
        nickname=_TEST_ACCOUNT_NICKNAME,
    )
    await session.commit()

    _set_session_cookie(response, user.id)
    return _to_response(user)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(ACCESS_TOKEN_COOKIE)
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return _to_response(user)
