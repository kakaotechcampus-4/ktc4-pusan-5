"""환경변수 설정. 비밀키는 여기서만 읽는다.

`database_url` 기본값을 backend/app/core/config.py 와 **같게** 맞춘다.
같은 Postgres 를 보라는 뜻이다. 다르면 표가 두 DB 로 갈라져서, 나중에 API 가
리포트를 못 찾는데 원인은 안 보이는 상태가 된다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.telegram"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://basis:basis@localhost:5432/basis"

    # 네이버 증권 리서치는 인증이 없어서 키가 필요 없다.
    # 남의 서버이고 PDF 가 수십 MB 라 타임아웃은 넉넉히 준다.
    http_timeout_sec: float = 30.0

    # 텔레그램은 공개 API 가 없다. 개인 계정으로 로그인해서 채널을 읽는 방식뿐이다.
    #
    # ⚠️ telegram_session 은 API 키가 아니라 **로그인된 계정 그 자체**다.
    #    이게 유출되면 그 계정으로 채팅을 읽고 메시지를 보내고 그룹을 나갈 수 있다.
    #    .env 에만 두고 절대 커밋하지 않는다. 세션 파일(.session)도 만들지 않는다 —
    #    파일로 두면 실수로 커밋되거나 이미지에 딸려 들어간다. 문자열로 환경변수에 둔다.
    #
    # api_id·api_hash 는 my.telegram.org 에서 받는다. 이 둘만으로는 아무것도 못 한다.
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str | None = None

    # 텔레그램 리포트 요약 생성. 네이버는 API 가 요약을 줘서 필요 없다(5종 100/100 확인).
    #
    openrouter_api_key: str | None = None
    summary_model: str = "deepseek/deepseek-v4-flash-0731"
    # 추론 모델이라 내용을 쓰기 전에 reasoning 토큰을 1,000~1,500 쓴다. max_tokens 는
    # reasoning + content 합계라 1,200 으로 잡았더니 40건 중 21건이 빈 응답이었다.
    summary_max_tokens: int = 8000
    # 기본 모델은 고강도 추론이 기본값이다. 짧은 요약에는 low로 시간을 제한한다.
    summary_reasoning_effort: str | None = "low"
    summary_timeout_sec: float = 180.0

    def require_openrouter(self) -> str:
        if not self.openrouter_api_key:
            raise RuntimeError(
                "요약 생성에 OPENROUTER_API_KEY 가 필요하다. ai/.env 에 넣는다."
            )
        return self.openrouter_api_key

    def require_telegram(self, *, require_session: bool = True) -> None:
        """텔레그램 설정이 없으면 여기서 멈춘다.

        없는 채로 Telethon 에 넘기면 `TypeError: 'NoneType'` 처럼 원인을 알 수 없는
        곳에서 죽는다. 뭘 채워야 하는지 알려주고 멈추는 게 낫다.
        """
        missing = [
            name
            for name in (("telegram_api_id", "telegram_api_hash", "telegram_session")
                         if require_session else ("telegram_api_id", "telegram_api_hash"))
            if not getattr(self, name) or (isinstance(getattr(self, name), str)
                                         and not getattr(self, name).strip())
        ]
        if missing:
            raise RuntimeError(
                "텔레그램 수집에 필요한 설정이 없다: "
                + ", ".join(n.upper() for n in missing)
                + "\n  ai/.env 에 넣는다. api_id·api_hash 는 my.telegram.org 에서 받고,"
                " 세션 문자열은 README 의 발급 방법을 따른다."
            )


settings = Settings()
