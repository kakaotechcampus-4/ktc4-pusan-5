"""리포트 요약 모델 호출.

모델·엔드포인트·인증과 응답 처리를 한 곳에서 관리한다.
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
    key = settings.require_openrouter()
    payload = {
        "model": model or settings.summary_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens or settings.summary_max_tokens,
    }
    if settings.summary_reasoning_effort == "none":
        payload["reasoning"] = {"enabled": False}
    elif settings.summary_reasoning_effort is not None:
        payload["reasoning"] = {"effort": settings.summary_reasoning_effort}
    try:
        # OpenRouter가 대기용 바이트를 계속 보내면 HTTP read timeout은 매번
        # 초기화된다. 연결부터 응답 완료까지의 전체 시간도 제한한다.
        async with (
            asyncio.timeout(settings.summary_timeout_sec),
            httpx.AsyncClient(timeout=settings.summary_timeout_sec) as client,
        ):
            r = await client.post(
                OPENROUTER_URL,
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        raise LLMError(f"LLM 호출 실패: {type(exc).__name__}") from exc

    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    usage = dict(data.get("usage") or {})
    usage["finish_reason"] = choice.get("finish_reason")
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
