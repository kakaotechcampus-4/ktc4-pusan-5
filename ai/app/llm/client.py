"""리포트 요약 모델 호출.

모델·엔드포인트·인증과 응답 처리를 한 곳에서 관리한다.

프로바이더는 둘이다. 기본은 OpenRouter 이고, `.env` 에 `LLM_PROVIDER=elice` 를
두면 카카오테크캠퍼스 Elice ML API(팀 예산)로 보낸다. 둘 다 OpenAI 호환이지만
받는 매개변수 이름이 달라서 `_payload` 에서 가른다.
"""

import asyncio
import json
import logging
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_DIR = Path(__file__).parent / "prompts"
# 오류 응답 본문은 로그 한 줄에 들어갈 만큼만 남긴다.
ERROR_BODY_MAX_CHARS = 300


class LLMError(Exception):
    """LLM 호출 실패. 원인 예외는 __cause__ 에 남는다."""


def load_prompt(name: str) -> str:
    """`prompts/<name>.md` 를 읽는다.

    프롬프트를 코드 밖에 두는 이유는 이게 **코드가 아니라 문서**라서다.
    팀원이 파이썬을 안 열고도 읽고 고칠 수 있어야 하고, 고쳤을 때 diff 가
    문장 단위로 보여야 한다.
    """
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise LLMError(f"프롬프트가 없다: {path}")
    return path.read_text(encoding="utf-8").strip()


def endpoint() -> tuple[str, str]:
    """(요청 주소, 키). 설정이 빠졌으면 RuntimeError.

    호출 전에 따로 불러 볼 수 있게 밖에 둔다. 수백 건을 돌리는 쪽이 첫 호출에서야
    키가 없다는 걸 알면, 그 앞의 수집 시간이 헛돈다.
    """
    if settings.llm_provider == "elice":
        base, key = settings.require_elice()
        return f"{base}/chat/completions", key
    return OPENROUTER_URL, settings.require_openrouter()


def _payload(system: str, user: str, model: str | None, max_tokens: int | None,
             temperature: float) -> dict:
    """프로바이더마다 받는 매개변수 이름이 다르다.

    Elice 는 **모르는 매개변수를 400 으로 거절한다.** 그래서 OpenRouter 형식에 필드를
    덧붙이는 식으로 못 하고 아예 갈라서 만든다.

        OpenRouter  max_tokens             reasoning: {"effort": ...} / {"enabled": False}
        Elice       max_completion_tokens  reasoning_effort: "minimal" | "low" | ...
    """
    payload = {
        "model": model or settings.summary_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    limit = max_tokens or settings.summary_max_tokens
    effort = settings.summary_reasoning_effort
    if settings.llm_provider == "elice":
        payload["max_completion_tokens"] = limit
        # 허용값은 모델마다 다르다(gemini-3.5-flash-lite 는 minimal·low·medium·high).
        # 없는 값은 Elice 가 400 으로 알려주므로 여기서 바꿔 끼우지 않는다.
        if effort is not None:
            payload["reasoning_effort"] = effort
        return payload
    payload["max_tokens"] = limit
    if effort == "none":
        payload["reasoning"] = {"enabled": False}
    elif effort is not None:
        payload["reasoning"] = {"effort": effort}
    return payload


def _elice_cost(usage: dict) -> float:
    """Elice 는 응답에 비용을 안 준다. 설정한 단가로 계산한다."""
    return (usage.get("prompt_tokens", 0) * settings.llm_input_usd_per_m
            + usage.get("completion_tokens", 0) * settings.llm_output_usd_per_m) / 1_000_000


async def complete(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> tuple[str, dict]:
    """(응답 텍스트, 사용량). 실패하면 LLMError.

    `temperature` 기본값이 0.2 다. 0 이 아닌 이유는 이 모델이 0 에서 같은 문장을
    두 번 쓰는 경우가 있어서다. 요약은 창작이 아니라 낮게 둔다.
    """
    url, key = endpoint()
    payload = _payload(system, user, model, max_tokens, temperature)
    try:
        # OpenRouter가 대기용 바이트를 계속 보내면 HTTP read timeout은 매번
        # 초기화된다. 연결부터 응답 완료까지의 전체 시간도 제한한다.
        async with (
            asyncio.timeout(settings.summary_timeout_sec),
            httpx.AsyncClient(timeout=settings.summary_timeout_sec) as client,
        ):
            r = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        # 상태 코드와 응답 앞부분을 남긴다. 예외 이름만 남기면 429(속도 제한)인지
        # 400(매개변수 거절)인지 몰라서 고칠 곳을 못 찾는다 — Elice 첫 실행에서 겪었다.
        # 응답 본문은 프로바이더의 오류 메시지라 키가 들어 있지 않다.
        raise LLMError(
            f"LLM 호출 실패: HTTP {exc.response.status_code} "
            f"{exc.response.text[:ERROR_BODY_MAX_CHARS]}"
        ) from exc
    except (httpx.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        raise LLMError(f"LLM 호출 실패: {type(exc).__name__}") from exc

    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    usage = dict(data.get("usage") or {})
    usage["finish_reason"] = choice.get("finish_reason")
    if settings.llm_provider == "elice" and "cost" not in usage:
        # cost_usd 가 OpenRouter 의 usage.cost 를 먼저 보므로 같은 자리에 넣어 둔다.
        # 안 넣으면 cost_usd 가 deepseek 단가로 추정해 1/5~1/20 로 낮게 잡는다.
        usage["cost"] = _elice_cost(usage)
    # 추론 모델이라 예산을 사고에 다 쓰면 본문이 빈 채로 정상 응답이 온다.
    # 조용히 넘어가면 빈 요약이 DB 에 쌓이므로 여기서 사유를 남긴다.
    if not text:
        logger.warning(
            "LLM 이 빈 응답을 줬다 (finish_reason=%s, usage=%s)",
            choice.get("finish_reason"), usage,
        )
    return text, usage


def cost_usd(usage: dict) -> float:
    """프로바이더가 반환한 비용을 우선 사용하고, 없으면 토큰으로 추정한다.

    deepseek-v4-flash-0731 기준 입력 $0.06/M, 출력 $0.12/M 로 계산한다.
    302건 돌렸을 때 $0.71 이 나왔고 실제 청구액과 자릿수가 맞았다.
    """
    if isinstance(usage.get("cost"), (int, float)):
        return float(usage["cost"])
    return usage.get("prompt_tokens", 0) * 6e-8 + usage.get("completion_tokens", 0) * 1.2e-7
