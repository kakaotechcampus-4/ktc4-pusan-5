"""환경변수 설정. 비밀키는 여기서만 읽는다 (backend/CLAUDE.md)."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "BASIS API"
    cors_origins: list[str] = ["http://localhost:5173"]
    database_url: str = "postgresql+asyncpg://basis:basis@localhost:5432/basis"

    # 외부 API 키. 네이버 뉴스 검색 키는 뉴스 수집과 함께 ai/ 로 옮겼다.
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_env: str = "real"
    kis_api_base_url: str = "https://openapi.koreainvestment.com:9443"
    # KIS 요청 사이 간격(초). 공식 한도는 계좌(앱키)당 초당 18건이지만 신규 신청 후 3일은 초당 3건이고,
    # 실측으로는 1초 간격에서만 안정적이었다. 신규 제한이 풀리면 다시 측정해 줄인다.
    kis_request_interval_seconds: float = Field(default=1.0, gt=0)
    fred_api_key: str = ""
    fred_api_base_url: str = "https://api.stlouisfed.org/fred"
    krx_auth_key: str = ""
    krx_api_base_url: str = "https://data-dbg.krx.co.kr/svc/apis"
    dart_api_key: str = ""
    ecos_api_key: str = ""

    # 수집기가 고정 목록 종목의 현재가를 다시 받는 장중 주기(초). 장외에는 마감 후 한 번만 받는다.
    # 종목 수 × kis_request_interval_seconds 가 이 값의 절반을 넘으면 차트·재무 작업이 밀린다.
    stock_quote_interval_seconds: int = Field(default=60, ge=15)
    # 기관 순매수를 다시 받는 장중 주기(초). 장외에는 마감 후 한 번만 받는다.
    stock_investor_interval_seconds: int = Field(default=3600, ge=60)

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

    # Sentry 에러 수집. DSN 이 비면 Sentry 는 꺼진다(로컬·CI·테스트 기본값).
    # 운영 서버 .env 에서 SENTRY_ENVIRONMENT=production. release 는 배포 때 주입할 예정이고 비어도 동작한다.
    sentry_dsn: str = ""
    sentry_environment: str = "local"
    sentry_release: str = ""

    @model_validator(mode="after")
    def _forbid_test_login_outside_local(self) -> "Settings":
        if self.enable_test_login and self.app_env != "local":
            raise ValueError(
                "ENABLE_TEST_LOGIN=true 는 APP_ENV=local 에서만 허용됩니다 "
                f"(현재 APP_ENV={self.app_env})"
            )
        return self


settings = Settings()
