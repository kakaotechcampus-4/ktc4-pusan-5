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


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        nickname=user.nickname,
        email=user.email,
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

    if kakao_user.email is None:
        raise AppError(
            "KAKAO_EMAIL_REQUIRED", "카카오 계정의 이메일 동의가 필요합니다", status_code=401
        )

    user = await get_or_create_user(
        session,
        kakao_id=kakao_user.kakao_id,
        nickname=kakao_user.nickname,
        email=kakao_user.email,
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
