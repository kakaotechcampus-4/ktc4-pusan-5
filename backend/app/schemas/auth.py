from app.schemas.base import CamelModel


class KakaoLoginRequest(CamelModel):
    code: str


class UserResponse(CamelModel):
    id: int
    nickname: str
    email: str
