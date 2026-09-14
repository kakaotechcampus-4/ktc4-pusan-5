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


settings = Settings()
