"""③ 보고서 생성과 ④ 실행 기록 래핑.

입력 JSON 하나 → `complete()` 한 번 → 래퍼 dict 하나. 래퍼는 적재 모듈의
`parse_wrapper()` 가 읽는 형식이다(필드 뜻은 그 모듈 docstring 참고).

입력은 파일이 아니라 **dict 로 받는다.** 지금은 CLI 가 파일을 열어 넘기지만, ② 필터·
태깅이 붙으면 DB 에서 만든 dict 를 그대로 넘길 수 있게 하려는 것이다.

## final_text 에 무엇을 넣나

`parse_wrapper()` 는 final_text 를 그대로 `json.loads` 한다. 그래서 코드펜스를 벗겨야
열린 응답(stripped)은 **벗겨낸 JSON 텍스트**를 넣고, 모델이 낸 원문은 raw_text 에 따로
남긴다. 원문을 final_text 에 넣으면 벗기면 멀쩡한 보고서가 전부 parse_failed 가 된다.
그래도 json_status=stripped 가 남으므로 적재는 schema_violation 으로 표시해 화면에 내지 않는다.

## 실패를 예외로 올리지 않는다

LLM 호출 실패·빈 응답은 is_error=true 래퍼로 돌려준다. 여러 입력을 도는 중에 한 건이
죽었다고 뒤의 건까지 멈추면 안 되고, 실패한 회차도 "왜 실패했나" 를 남겨야 한다.
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.llm.client import PROMPT_DIR, LLMError, complete, cost, cost_currency
from app.repositories.stock_move_analysis import KST
from app.services.stock_analysis.verify import EMPTY_RESPONSE, LLM_ERROR, check_schema

logger = logging.getLogger(__name__)

PROMPT_NAME = "stock_analysis_system"

# 프롬프트 1부 입력 형식에서 러너가 반드시 있어야 하는 칸. market 은 null 이 허용이라
# 빠져 있다. change_pct 는 ±1% 규칙과 초과분 판단의 기준이라 없으면 검증을 못 한다.
REQUIRED_INPUT = ("stock", "code", "target_date", "cutoff", "change_pct", "messages")

_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\n(.*?)```", re.DOTALL)
# Windows 파일명에 못 쓰는 글자와 공백. run_id 는 파일명이 된다.
_UNSAFE = re.compile(r'[<>:"/\\|?*\s]+')
_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def prompt_sha256() -> str:
    """시스템 프롬프트 **파일 바이트**의 해시. 어떤 판으로 만든 보고서인지 가리는 키다.

    load_prompt() 의 반환값이 아니라 파일을 해시하는 이유: load_prompt 는 앞뒤 공백을
    걷어내므로, 파일을 열어 sha256sum 한 값과 맞춰 볼 수 있어야 추적이 된다.
    """
    return hashlib.sha256((PROMPT_DIR / f"{PROMPT_NAME}.md").read_bytes()).hexdigest()


def check_input(payload: Any) -> list[str]:
    """호출 전에 입력을 본다. 돈을 쓰고 나서 입력이 깨져 있었다는 걸 알면 헛돈다."""
    if not isinstance(payload, dict):
        return [f"입력이 객체가 아니다: {type(payload).__name__}"]
    problems = [f"{key} 가 없다" for key in REQUIRED_INPUT if key not in payload]
    change = payload.get("change_pct")
    if "change_pct" in payload and (isinstance(change, bool) or not isinstance(change, (int, float))):
        problems.append(f"change_pct 는 숫자여야 한다: {change!r}")
    if "messages" in payload and not isinstance(payload["messages"], list):
        problems.append("messages 는 배열이어야 한다")
    return problems


def _cutoff_hhmm(cutoff: Any) -> str:
    if isinstance(cutoff, str):
        try:
            return datetime.fromisoformat(cutoff.strip()).strftime("%H%M")
        except ValueError:
            pass
        m = _HHMM.search(cutoff)
        if m:
            return f"{int(m.group(1)):02d}{m.group(2)}"
    return "cutoff"


def make_run_id(payload: dict[str, Any], repeat: int = 1) -> str:
    """`<종목>-<날짜>-<기준시각 HHMM>__r<반복>`.

    기존 산출물의 `<종목>-<날짜>-<조건>__<반복>` 꼴을 따랐다. 조건 자리에 기준 시각을
    넣은 건 같은 날 같은 종목이 시각별로 여러 판 나오기 때문이다. 같은 판을 다시 돌리면
    반복 번호로 가른다(부르는 쪽이 정한다).
    """
    stock = _UNSAFE.sub("_", str(payload.get("stock") or payload.get("code") or "unknown"))
    return f"{stock}-{payload.get('target_date')}-{_cutoff_hhmm(payload.get('cutoff'))}__r{repeat}"


def extract_json(text: str) -> tuple[str, dict[str, Any] | None, str]:
    """(json_status, 보고서, final_text 에 넣을 텍스트).

        clean     응답 그대로 JSON 객체
        stripped  코드펜스나 머리말·꼬리말을 벗겨야 열린다
        invalid   그래도 안 열린다. 보고서는 None, 텍스트는 원문 그대로
    """
    body = text.strip()
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return "clean", parsed, body
    except json.JSONDecodeError:
        pass

    candidates = [m.group(1).strip() for m in _FENCE.finditer(body)]
    start, end = body.find("{"), body.rfind("}")
    if start != -1 and end > start:
        candidates.append(body[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return "stripped", parsed, candidate
    return "invalid", None, body


def looks_like_question(text: str) -> bool:
    """되물었나. 프롬프트가 금지하지만 정보가 부족하면 모델이 질문으로 끝내는 날이 있다."""
    return text.rstrip().endswith(("?", "？"))


def report_of(wrapper: dict[str, Any]) -> dict[str, Any] | None:
    """래퍼에서 보고서를 다시 편다. 열린 회차(clean·stripped)만."""
    if wrapper.get("is_error") or wrapper.get("json_status") not in ("clean", "stripped"):
        return None
    report = json.loads(wrapper["final_text"])
    return report if isinstance(report, dict) else None


async def generate(
    payload: dict[str, Any], *, system: str, prompt_hash: str, run_id: str
) -> dict[str, Any]:
    """입력 하나로 보고서를 만들어 래퍼로 감싼다. 예외를 던지지 않는다.

    모델·토큰 상한·타임아웃은 `complete()` 가 settings 에서 읽는다. 래퍼의 model 도
    같은 settings 값을 적는다 — complete 를 model 인자 없이 부르므로 둘이 같다.
    """
    started = time.monotonic()
    wrapper: dict[str, Any] = {
        "run_id": run_id,
        "final_text": "",
        "json_status": None,
        "schema_problems": [],
        "is_error": False,
        "asked_question": False,
        # 실패 종류. 검증 사유 코드로 그대로 쓴다(verify.verify_wrapper).
        "error_code": None,
        "error": None,
        # clean 이 아닐 때만 채운다. clean 이면 final_text 와 같아서 두 번 담을 이유가 없다.
        "raw_text": None,
        # 운영 지표. 적재 모듈은 이 아래를 읽지 않는다(보고서 표에 넣지 않기로 했다).
        "provider": settings.llm_provider,
        "model": settings.summary_model,
        "usage": {},
        # 통화는 프로바이더마다 다르다(OpenRouter 달러, Elice 원화). 숫자만 두면 합산할 때 섞인다.
        "cost": 0.0,
        "cost_currency": cost_currency(),
        "duration_ms": 0,
        "prompt_name": PROMPT_NAME,
        "prompt_sha256": prompt_hash,
        # 래퍼에 생성 시각이 없어 실행 디렉터리 이름에 기대던 것을 여기 직접 남긴다.
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        text, usage = await complete(system, user)
    except LLMError as exc:
        logger.warning("%s: %s", run_id, exc)
        wrapper.update(is_error=True, error_code=LLM_ERROR, error=str(exc))
        wrapper["duration_ms"] = round((time.monotonic() - started) * 1000)
        return wrapper

    wrapper["usage"] = usage
    wrapper["cost"] = cost(usage)
    wrapper["duration_ms"] = round((time.monotonic() - started) * 1000)

    if not text:
        # 추론 모델이 예산을 사고에 다 쓰면 빈 본문이 정상 응답으로 온다. 비용은 나갔으니
        # usage·cost 는 남기고 실행 실패로 표시한다.
        wrapper.update(
            is_error=True, json_status="invalid", error_code=EMPTY_RESPONSE,
            error=f"빈 응답 (finish_reason={usage.get('finish_reason')})",
        )
        return wrapper

    status, report, final_text = extract_json(text)
    wrapper["json_status"] = status
    wrapper["final_text"] = final_text
    if status != "clean":
        wrapper["raw_text"] = text
    if report is None:
        wrapper["asked_question"] = looks_like_question(text)
    else:
        wrapper["schema_problems"] = check_schema(report)
    return wrapper


__all__ = [
    "PROMPT_NAME",
    "check_input",
    "extract_json",
    "generate",
    "looks_like_question",
    "make_run_id",
    "prompt_sha256",
    "report_of",
]
