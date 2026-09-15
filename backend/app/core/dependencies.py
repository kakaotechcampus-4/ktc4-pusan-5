# 라우터에서 쓰는 공용 Depends

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import ACCESS_TOKEN_COOKIE, decode_access_token
from app.models import User
from app.repositories.user import get_by_id


# 쿠키에서 토큰 추출 → 검증 → DB 조회 흐름에서 실패하면 AppError로 raise
async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token is None:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다", status_code=401)

    try:
        user_id = decode_access_token(token)
    except jwt.PyJWTError as e:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다", status_code=401) from e

    user = await get_by_id(session, user_id)
    if user is None:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다", status_code=401)
    return user
