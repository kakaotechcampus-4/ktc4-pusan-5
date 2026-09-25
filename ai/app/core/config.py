"""환경변수 설정. 비밀키는 여기서만 읽는다.

`database_url` 기본값을 backend/app/core/config.py 와 **같게** 맞춘다.
같은 Postgres 를 보라는 뜻이다. 다르면 표가 두 DB 로 갈라져서, 나중에 API 가
리포트를 못 찾는데 원인은 안 보이는 상태가 된다.
"""

from typing import Literal

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

    # LLM 을 어디로 보내나. **기본은 openrouter 다** — 이 줄이 없는 .env 는 동작이 안 바뀐다.
    #   openrouter  OPENROUTER_API_KEY 로 보낸다. 비용은 응답의 usage.cost 를 쓴다
    #   elice       카카오테크캠퍼스 Elice ML API(팀 예산). LLM_BASE_URL·LLM_API_KEY 로 보낸다
    #
    # Elice 는 목록에 없는 매개변수를 무시하지 않고 400 으로 거절한다. OpenRouter 전용인
    # max_tokens·reasoning 을 그대로 보내면 안 되는 이유다(client.py 가 형식을 가른다).
    llm_provider: Literal["openrouter", "elice"] = "openrouter"
    # 모델마다 주소가 따로 있다. 모델 페이지 예시 코드의 https://mlapi.run/<ID> 에 /v1 을 붙인다.
    # ID 없는 https://mlapi.run/v1 로 보내면 500 이 난다(2026-09-25 확인).
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    # Elice 는 응답에 비용을 주지 않는다. 모델 페이지의 1M 토큰당 달러 단가로 계산한다.
    # 기본값은 gemini-3.5-flash-lite(입력 $0.3 · 출력 $2.5). 모델을 바꾸면 같이 바꾼다.
    llm_input_usd_per_m: float = 0.3
    llm_output_usd_per_m: float = 2.5

    def require_elice(self) -> tuple[str, str]:
        """(주소, 키). 빠진 게 있으면 무엇을 채울지 알려주고 멈춘다."""
        missing = [name.upper() for name in ("llm_base_url", "llm_api_key")
                   if not (getattr(self, name) or "").strip()]
        if missing:
            raise RuntimeError(
                "LLM_PROVIDER=elice 인데 설정이 없다: " + ", ".join(missing)
                + "\n  ai/.env 에 넣는다. 주소는 모델 페이지 예시 코드의 https://mlapi.run/<ID>/v1 이다."
            )
        return self.llm_base_url.strip().rstrip("/"), self.llm_api_key.strip()

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
