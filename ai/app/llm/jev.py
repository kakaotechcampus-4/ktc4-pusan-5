"""Jev(TypeSafe, Elice 경유) 판단 호출 한 번.

채팅 API 가 아니다. 판단할 내용(state)과 질문(questions)을 보내면 질문 이름마다 정해진 형식의
답(answers)이 온다. 글을 쓰지 않으므로 사건 추출처럼 목록을 만들어야 하는 일에는 못 쓰고,
표기 연결·묶기·판정처럼 정해진 선택지에서 고르는 일에 쓴다.

    질문 형식  choice  criteria 의 키 중 하나를 고른다. confidence·probabilities 가 함께 온다
              noul    참일 확률
              score   criteria 배열의 순서형 점수

과금은 입력 토큰(usage.prompt_tokens)만이다. 스트리밍은 지원하지 않는다.
설정은 config.py 의 JEV_* 다. 오류는 client.py 와 같은 LLMError 계열로 올린다.
"""

import asyncio
import json

import httpx

from app.core.config import settings
from app.llm.client import LLMError, LLMRateLimited, LLMTimeout, _error_detail


def endpoint() -> tuple[str, str]:
    """(요청 주소, 키). 설정이 빠졌으면 RuntimeError. 자료를 읽기 전에 불러 확인할 수 있게 밖에 둔다."""
    url, key, _ = settings.require_jev()
    return url, key


def cost(usage: dict) -> float:
    """원화 비용. 출력은 과금되지 않아 입력 토큰만 곱한다."""
    _, _, rate = settings.require_jev()
    tokens = usage.get("prompt_tokens")
    tokens = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else 0
    return tokens * rate / 1_000_000


def _parse(data: object, key: str) -> tuple[dict, dict]:
    """응답 → (answers, usage). 모양이 다르면 LLMError. 호출부는 LLMError 만 잡는다."""
    if not isinstance(data, dict):
        raise LLMError("Jev 응답 형식 오류: JSON 객체가 아니다")
    answers = data.get("answers")
    if not isinstance(answers, dict) or not all(isinstance(a, dict) for a in answers.values()):
        error = data.get("error")
        detail = _error_detail(json.dumps(error, ensure_ascii=False), key) if error else ""
        raise LLMError(f"Jev 응답 형식 오류: answers 가 없다 {detail}".rstrip())
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        raise LLMError("Jev 응답 형식 오류: usage 가 객체가 아니다")
    return answers, dict(usage)


async def decide(state: object, questions: dict[str, dict], *,
                 model: str | None = None) -> tuple[dict, dict]:
    """(answers, usage). 실패하면 LLMError, 429 면 LLMRateLimited, 시간 초과면 LLMTimeout.

    usage 에는 쓴 모델과 원화 비용 근거를 붙인다. 회차 usage 칸에 그대로 남길 수 있다.
    """
    if not questions:
        raise ValueError("질문이 없다")
    url, key = endpoint()
    payload = {"model": model or settings.jev_model, "state": state, "questions": questions}
    try:
        async with (
            asyncio.timeout(settings.jev_timeout_sec),
            httpx.AsyncClient(timeout=settings.jev_timeout_sec) as client,
        ):
            r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            answers, usage = _parse(r.json(), key)
    except httpx.HTTPStatusError as exc:
        error = LLMRateLimited if exc.response.status_code == 429 else LLMError
        raise error(
            f"Jev 호출 실패: HTTP {exc.response.status_code} "
            f"{_error_detail(exc.response.text, key)}"
        ) from exc
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise LLMTimeout(f"Jev 호출 실패: {type(exc).__name__} ({settings.jev_timeout_sec:g}초 제한)") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise LLMError(f"Jev 호출 실패: {type(exc).__name__}") from exc

    usage["model"] = payload["model"]
    usage["cost_currency"] = "KRW"
    return answers, usage
