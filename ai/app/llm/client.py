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


class LLMTimeout(LLMError):
    """호출 전체 시간 제한(settings.summary_timeout_sec)이나 연결 시간 제한에 걸렸다. 받은 부분은 없다."""


class StreamInterrupted(LLMError):
    """스트림이 응답을 다 주기 전에 끊겼다. 받은 부분은 길이(글자 수)만 남긴다 —
    잘린 JSON 을 열어 보거나 저장하면 안 되므로 본문은 넘기지 않는다."""

    def __init__(self, message: str, partial_chars: int):
        super().__init__(message)
        self.partial_chars = partial_chars


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
             temperature: float | None) -> dict:
    """프로바이더마다 받는 매개변수 이름이 다르다.

    Elice 는 **모르는 매개변수를 400 으로 거절한다.** 그래서 OpenRouter 형식에 필드를
    덧붙이는 식으로 못 하고 아예 갈라서 만든다.

        OpenRouter  max_tokens             reasoning: {"effort": ...} / {"enabled": False}
        Elice       max_completion_tokens  reasoning_effort: "minimal" | "low" | ...

    temperature 가 None 이면 필드를 넣지 않는다. 기본값만 받는 모델에 null 을 보내도
    거절될 수 있어서, "안 보냄" 은 키 자체를 빼는 것으로 표현한다.
    """
    payload = {
        "model": model or settings.summary_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if temperature is not None:
        payload["temperature"] = temperature
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


# 캐시 쓰기가 있는 호출에서 prompt_tokens 에 얹히는 몫(쓰기 토큰 대비). 2026-10-09 Elice
# (gpt-6-luna)에서 같은 요청을 두 번 보내 확인했다. 세 쌍 모두 첫 호출의 prompt_tokens 가
# 두 번째보다 정확히 round(cache_write_tokens × 0.25) 많았고, 두 번째 호출은
# cached_tokens + 캐시 미적용분 = prompt_tokens 였다. 예: 10887 = 8710 + round(8707 × 0.25).
# 즉 prompt_tokens 는 입력 토큰 수가 아니라 쓰기 할증이 섞인 값이다. OpenRouter 는 확인하지
# 않았다 — 비용을 응답으로 주므로 이 값은 토큰 내역 표시에만 쓰인다.
CACHE_WRITE_PROMPT_SURCHARGE = {"elice": 0.25}


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def input_tokens(usage: dict) -> dict[str, int]:
    """입력 토큰 내역. total = cache_read + cache_write + uncached.

        reported     응답의 prompt_tokens 그대로
        total        실제 입력 토큰 수. reported 에서 캐시 쓰기 할증을 뺀 값
        cache_read   캐시에서 읽은 토큰 (prompt_tokens_details.cached_tokens)
        cache_write  캐시에 새로 쓴 토큰 (prompt_tokens_details.cache_write_tokens)
        uncached     캐시를 거치지 않은 토큰

    캐시 칸이 없는 응답은 둘 다 0 이라 total = reported = uncached 다.
    """
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    read = _int(details.get("cached_tokens")) or _int(usage.get("cached_prompt_tokens"))
    write = _int(details.get("cache_write_tokens")) or _int(usage.get("cache_write_tokens"))
    reported = _int(usage.get("prompt_tokens"))
    surcharge = round(write * CACHE_WRITE_PROMPT_SURCHARGE.get(settings.llm_provider, 0.0))
    total = max(reported - surcharge, read + write)
    return {"reported": reported, "total": total, "cache_read": read, "cache_write": write,
            "uncached": total - read - write}


def _token_cost(usage: dict) -> float:
    rates = settings.token_rates()
    tokens = input_tokens(usage)
    return (tokens["uncached"] * rates["input"] + tokens["cache_read"] * rates["cache_read"]
            + tokens["cache_write"] * rates["cache_write"]
            + _int(usage.get("completion_tokens")) * rates["output"]) / 1_000_000


async def complete(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> tuple[str, dict]:
    """(응답 텍스트, 사용량). 실패하면 LLMError, 스트림이 중간에 끊기면 StreamInterrupted.

    `stream` 은 기본이 False 다. 부르는 쪽이 켤 때만 스트리밍으로 받는다 — 리포트 요약
    (analyst)은 넘기지 않으므로 지금처럼 한 번에 받는다. 스트리밍이면 usage 는 마지막
    이벤트로 온다(stream_options.include_usage). 그게 안 오면 usage 에 토큰 칸이 없다.

    `temperature` 기본값이 0.2 다(`settings.llm_temperature`). 0 이 아닌 이유는 이 모델이
    0 에서 같은 문장을 두 번 쓰는 경우가 있어서다. 요약은 창작이 아니라 낮게 둔다.

    다만 추론 모델은 temperature 를 받지 않을 수 있다. Elice 의 luna 는 기본값(1) 말고는
    400 으로 거절한다. 그런 모델은 `.env` 에 `LLM_TEMPERATURE=` 로 비워 두면 요청에서
    필드가 빠진다. 호출하는 쪽이 값을 넘기면 설정보다 그 값을 우선한다.
    """
    url, key = endpoint()
    if temperature is None:
        temperature = settings.llm_temperature
    payload = _payload(system, user, model, max_tokens, temperature)
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    try:
        # OpenRouter가 대기용 바이트를 계속 보내면 HTTP read timeout은 매번
        # 초기화된다. 연결부터 응답 완료까지의 전체 시간도 제한한다.
        async with (
            asyncio.timeout(settings.summary_timeout_sec),
            httpx.AsyncClient(timeout=settings.summary_timeout_sec) as client,
        ):
            headers = {"Authorization": f"Bearer {key}"}
            if stream:
                async with client.stream("POST", url, json=payload, headers=headers) as r:
                    if r.is_error:
                        await r.aread()  # 오류 본문을 메시지에 남기려면 먼저 읽어야 한다
                    r.raise_for_status()
                    text, finish_reason, usage = await _read_stream(r)
            else:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                choice = (data.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("content") or ""
                finish_reason = choice.get("finish_reason")
                usage = dict(data.get("usage") or {})
    except httpx.HTTPStatusError as exc:
        # 상태 코드와 응답 앞부분을 남긴다. 예외 이름만 남기면 429(속도 제한)인지
        # 400(매개변수 거절)인지 몰라서 고칠 곳을 못 찾는다 — Elice 첫 실행에서 겪었다.
        # 응답 본문은 프로바이더의 오류 메시지라 키가 들어 있지 않다.
        raise LLMError(
            f"LLM 호출 실패: HTTP {exc.response.status_code} "
            f"{exc.response.text[:ERROR_BODY_MAX_CHARS]}"
        ) from exc
    except (TimeoutError, httpx.TimeoutException) as exc:
        # 스트림을 읽는 중의 읽기 시간 초과는 _read_stream 이 StreamInterrupted 로 올린다. 여기 오는 것은
        # 전체 시간 제한(asyncio.timeout)이나 연결 단계의 시간 초과다.
        raise LLMTimeout(f"LLM 호출 실패: {type(exc).__name__} ({settings.summary_timeout_sec:g}초 제한)") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise LLMError(f"LLM 호출 실패: {type(exc).__name__}") from exc

    text = text.strip()
    usage["finish_reason"] = finish_reason
    # Elice 는 비용을 주지 않는다. 계산한 값을 usage.cost 에 넣지 않는다 — 그 자리는
    # 프로바이더가 준 값만 둬야 cost_basis 가 어느 쪽인지 가릴 수 있다.
    # usage 는 래퍼 등에 통째로 남는다. 숫자만 있으면 원인지 달러인지 나중에 알 수 없다.
    usage["cost_currency"] = cost_currency()
    # 추론 모델이라 예산을 사고에 다 쓰면 본문이 빈 채로 정상 응답이 온다.
    # 조용히 넘어가면 빈 요약이 DB 에 쌓이므로 여기서 사유를 남긴다.
    if not text:
        logger.warning(
            "LLM 이 빈 응답을 줬다 (finish_reason=%s, usage=%s)", finish_reason, usage,
        )
    return text, usage


async def _read_stream(response: httpx.Response) -> tuple[str, str | None, dict]:
    """SSE 를 끝까지 읽어 (본문, finish_reason, usage).

    `data:` 로 시작하지 않는 줄은 건너뛴다. 빈 줄은 이벤트 구분이고, `:` 로 시작하는 줄은
    OpenRouter 가 대기 중에 보내는 주석이다.

    끊긴 것으로 보는 경우 — 모두 StreamInterrupted 다.
        - 읽는 중 연결 오류(httpx.TransportError: 끊김·프로토콜 오류·읽기 시간 초과)
        - 이벤트가 JSON 이 아님, 또는 이벤트에 error 가 실려 옴(헤더가 이미 200 이라 HTTP
          상태로는 못 알린다)
        - finish_reason 없이 스트림이 끝남
    finish_reason 까지 받았으면 끝난 것이다. 그 뒤 usage 이벤트가 안 와도 끊김이 아니라
    usage 누락이다(빈 dict 를 돌려준다).
    """
    parts: list[str] = []
    finish_reason: str | None = None
    usage: dict = {}
    try:
        async for line in response.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if event.get("error"):
                raise StreamInterrupted(
                    f"스트림 중 오류: {str(event['error'])[:ERROR_BODY_MAX_CHARS]}",
                    len("".join(parts)))
            for choice in event.get("choices") or []:
                parts.append((choice.get("delta") or {}).get("content") or "")
                finish_reason = choice.get("finish_reason") or finish_reason
            if isinstance(event.get("usage"), dict):
                usage = dict(event["usage"])
    except (httpx.TransportError, json.JSONDecodeError) as exc:
        raise StreamInterrupted(f"스트림이 끊겼다: {type(exc).__name__}",
                                len("".join(parts))) from exc
    text = "".join(parts)
    if finish_reason is None:
        raise StreamInterrupted("스트림이 finish_reason 없이 끝났다", len(text))
    return text, finish_reason, usage


def cost_currency() -> str:
    """지금 설정의 비용 통화. OpenRouter 는 달러로 청구하고 usage.cost 도 달러다.
    Elice 는 모델 페이지 단가가 원화라 원화로 계산한다(config.py 참고).

    한 실행은 프로바이더 하나로만 돌기 때문에 실행 단위로 통화가 하나다.
    """
    return "KRW" if settings.llm_provider == "elice" else "USD"


def cost_detail(usage: dict) -> tuple[float, str]:
    """(비용, 근거). 통화는 `cost_currency()` 다.

        provider     응답의 usage.cost 를 그대로 (OpenRouter)
        token_rates  입력 내역(input_tokens)별로 settings.token_rates() 단가를 곱해서 (Elice)
        unavailable  응답에 비용도 토큰 수도 없다(스트림의 usage 누락). 비용은 0 으로 두지만
                     실제로 0 이라는 뜻이 아니다

    토큰으로 계산할 때 prompt_tokens 를 그대로 쓰지 않는다. 캐시 쓰기 할증이 섞여 있어
    첫 호출이 부풀려진다(CACHE_WRITE_PROMPT_SURCHARGE 참고).
    """
    if isinstance(usage.get("cost"), (int, float)) and not isinstance(usage["cost"], bool):
        return float(usage["cost"]), "provider"
    if "prompt_tokens" not in usage and "completion_tokens" not in usage:
        # 스트림이 usage 이벤트 없이 끝났다. 0 원으로 계산해 두면 공짜 호출처럼 보인다.
        return 0.0, "unavailable"
    return _token_cost(usage), "token_rates"


def cost(usage: dict) -> float:
    """비용. 근거까지 필요하면 `cost_detail()`."""
    return cost_detail(usage)[0]


def format_cost(amount: float, currency: str | None = None) -> str:
    """출력용. 원화는 한 건이 몇 원 단위라 소수 둘째 자리까지, 달러는 넷째 자리까지."""
    if (currency or cost_currency()) == "KRW":
        return f"₩{amount:,.2f}"
    return f"${amount:.4f}"
