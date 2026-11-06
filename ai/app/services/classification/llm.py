"""분류 단계의 LLM 호출 한 번. 단계마다 모델을 따로 줄 수 있다.

    extract  ① 사건 추출 (자료당 1회)
    link     ② 별칭에 안 걸린 표기를 코드 목록에서 고름 (그런 표기가 있을 때만)
    judge    ④ (사건, 후보 종목) 해당 여부 판정 (후보가 있을 때만)

모델은 호출 쪽이 넘긴 값 > `.env` 의 CLASSIFICATION_<단계>_MODEL > SUMMARY_MODEL 순서로 정한다.
단계마다 다른 모델을 써 보는 실험을 하려고 나눴다(예: 추출은 싼 모델, 판정은 큰 모델).
어떤 모델을 썼는지는 회차의 usage 에 단계별로 남는다(4-3 `usage`).

Elice 는 스트리밍이 아닌 요청의 출력 상한을 2,000 토큰으로 막는다(config.py). 판정 응답은 사건 ×
후보 수만큼 길어지므로 Elice 일 때는 스트리밍으로 받는다.

429 는 기다렸다 다시 보낸다. 판정에서 429 가 나 회차가 failed 가 되면 이미 비용을 쓴 추출까지 다시
해야 한다. 다른 오류는 다시 보내도 같거나 비용을 또 쓸 수 있어 그대로 실패로 남긴다.
"""

import asyncio
import hashlib
import logging
import random
from dataclasses import dataclass, field

from app.core.config import settings
from app.llm.client import LLMError, LLMRateLimited, complete, cost_detail, load_prompt

logger = logging.getLogger(__name__)
STEPS = ("extract", "link", "judge")
# 429 뒤 기다리는 초. 동시에 거절된 호출이 한꺼번에 다시 몰리지 않게 실제로는 1~1.5배로 흩는다
RATE_LIMIT_WAITS = (5, 20, 60)


@dataclass
class StepCall:
    step: str
    model: str
    prompt_sha256: str
    raw_response: str | None = None
    usage: dict = field(default_factory=dict)
    error: str | None = None
    rate_limit_retries: int = 0  # 429 로 다시 보낸 횟수

    @property
    def ok(self) -> bool:
        return self.error is None

    def usage_record(self) -> dict:
        """회차 usage 칸에 넣을 값. 모델과 비용을 함께 남긴다."""
        amount, basis = cost_detail(self.usage)
        return {**self.usage, "model": self.model, "cost": amount, "cost_basis": basis,
                "rate_limit_retries": self.rate_limit_retries}


def model_for(step: str, override: str | None = None) -> str:
    if step not in STEPS:
        raise ValueError(f"없는 단계: {step}")
    return override or getattr(settings, f"classification_{step}_model") or settings.summary_model


def prompt_sha256(prompt_name: str) -> str:
    return hashlib.sha256(load_prompt(prompt_name).encode("utf-8")).hexdigest()


async def call(step: str, prompt_name: str, user: str, *, model: str | None = None) -> StepCall:
    """실패해도 예외를 올리지 않고 error 에 남긴다. 회차를 failed 로 저장하려면 응답 원문이 필요하다."""
    system = load_prompt(prompt_name)
    result = StepCall(
        step=step, model=model_for(step, model),
        prompt_sha256=hashlib.sha256(system.encode("utf-8")).hexdigest(),
    )
    waits = iter(RATE_LIMIT_WAITS)
    while True:
        try:
            text, usage = await complete(
                system, user, model=result.model, max_tokens=settings.classification_max_tokens,
                stream=settings.llm_provider == "elice",
            )
        except LLMError as exc:
            wait = next(waits, None) if isinstance(exc, LLMRateLimited) else None
            if wait is None:
                result.error = f"{step}: {exc}"
                return result
            delay = wait * random.uniform(1, 1.5)
            result.rate_limit_retries += 1
            # 횟수는 회차 usage 와 합계 줄에 남는다. 로그는 긴 실행 도중에 429 를 알아채려고 찍는다
            logger.warning("429 %s: %.0f초 뒤 다시 보낸다", step, delay)
            await asyncio.sleep(delay)
            continue
        result.raw_response, result.usage = text, usage
        return result


def parse_failure(call_result: StepCall, message: str) -> str:
    """응답을 못 읽었을 때의 오류 문구. 출력 상한에 걸려 잘렸으면 그 사유도 붙인다."""
    finish = call_result.usage.get("finish_reason")
    suffix = f" (finish_reason={finish})" if finish not in (None, "stop") else ""
    return f"{call_result.step}: {message}{suffix}"
