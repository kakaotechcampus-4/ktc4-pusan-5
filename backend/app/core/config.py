"""환경변수 설정. 비밀키는 여기서만 읽는다 (backend/CLAUDE.md)."""

from typing import Literal

from pydantic import Field, model_validator
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
    kis_env: str = "real"
    kis_api_base_url: str = "https://openapi.koreainvestment.com:9443"
    fred_api_key: str = ""
    fred_api_base_url: str = "https://api.stlouisfed.org/fred"
    krx_auth_key: str = ""
    krx_api_base_url: str = "https://data-dbg.krx.co.kr/svc/apis"
    dart_api_key: str = ""
    ecos_api_key: str = ""

    # 카카오 로그인
    kakao_client_id: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = ""

    # 자체 세션(JWT). 미설정이나 32 이하 길이면 pydantic_core.ValidationError
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 20160  # 14일
    cookie_secure: bool = True  # 로컬 http 개발 환경에서만 .env 로 false 로 내린다

    # 실행 환경. 미설정이면 production 으로 간주한다(안전한 쪽이 기본값)
    app_env: Literal["local", "production"] = "production"

    # 로컬 개발용 테스트 로그인(/api/auth/test-login). local 환경에서만 켤 수 있다
    enable_test_login: bool = False

    @model_validator(mode="after")
    def _forbid_test_login_outside_local(self) -> "Settings":
        if self.enable_test_login and self.app_env != "local":
            raise ValueError(
                "ENABLE_TEST_LOGIN=true 는 APP_ENV=local 에서만 허용됩니다 "
                f"(현재 APP_ENV={self.app_env})"
            )
        return self


settings = Settings()
