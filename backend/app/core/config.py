"""환경변수 설정. 비밀키는 여기서만 읽는다 (backend/CLAUDE.md)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "BASIS API"
    cors_origins: list[str] = ["http://localhost:5173"]
    database_url: str = "postgresql+asyncpg://basis:basis@localhost:5432/basis"

    # 외부 API 키
    naver_client_id: str = ""
    naver_client_secret: str = ""
    kis_app_key: str = ""
    kis_app_secret: str = ""
    dart_api_key: str = ""
    ecos_api_key: str = ""

    # 카카오 로그인
    kakao_client_id: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = ""

    # 자체 세션(JWT)
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 20160  # 14일
    cookie_secure: bool = True  # 로컬 http 개발 환경에서만 .env 로 false 로 내린다



settings = Settings()
