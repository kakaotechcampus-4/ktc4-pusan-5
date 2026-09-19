"""환경변수 설정. 비밀키는 여기서만 읽는다.

`database_url` 기본값을 backend/app/core/config.py 와 **같게** 맞춘다.
같은 Postgres 를 보라는 뜻이다. 다르면 표가 두 DB 로 갈라져서, 나중에 API 가
리포트를 못 찾는데 원인은 안 보이는 상태가 된다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://basis:basis@localhost:5432/basis"

    # 네이버 증권 리서치는 인증이 없어서 키가 필요 없다.
    # 남의 서버이고 PDF 가 수십 MB 라 타임아웃은 넉넉히 준다.
    http_timeout_sec: float = 30.0


settings = Settings()
