"""세 가지 발췌 방식. 전부 (기사, 종목) 한 쌍을 받는다.

A·B 의 결과를 **문장 번호**로 맞춰 두는 이유는 채점을 자동으로 하려는 것이다.
사람이 적는 정답도 문장 번호라서, 번호끼리 비교하면 끝난다. C 는 새로 쓴 글이라
번호로 바꿀 수 없어서 사람이 채점한다.
"""

import json
import re

from app.llm.client import LLMError, complete, cost_usd, load_prompt
from app.services.analyst.summary import hallucinated_numbers
from app.services.news_link.fetch import DEFAULT_MAX_CHARS, DEFAULT_SENTENCES
from app.services.news_link.sentence import first_sentences, split_sentences

SELECT_PROMPT = "news_select"
SUMMARY_PROMPT = "news_summary"

# B 가 고를 수 있는 최대 문장 수. A(3문장)보다 한 칸 더 준다 — 가리키는 말("이 회사는")의
# 대상 문장을 함께 고르라고 시키기 때문이다. 더 넓히면 B 가 많이 골라서 이기는 것이지
# 잘 골라서 이기는 게 아니게 된다. 평균 글자 수를 리포트에 같이 싣는 이유다.
MAX_SELECT = 4

# 출력 토큰 상한. 설정 기본값(summary_max_tokens=8000)은 애널리스트 요약이 추론 모델에
# 맞춰 잡은 값이라 쓰지 않는다. Elice 는 6000 을 넘으면 400 으로 거절한다(2026-09-25 실측).
# 상한은 비용 상한이기도 하다. 추론 토큰도 출력으로 과금되므로 여유만 조금 둔다.
#   B  출력은 {"selected": [...]} 한 줄(~20토큰)
#   C  400자 요약(~350토큰)
SELECT_MAX_TOKENS = 1000
SUMMARY_MAX_TOKENS = 2000

_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)


def numbered(sentences: list[str]) -> str:
    """모델과 사람이 **같은 번호**를 보게 한다. sheet.md 도 이 함수로 찍는다."""
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))


def method_a(body: str) -> list[int]:
    """앞 3문장. 운영 코드(fetch.py)와 같은 함수·같은 상한으로 잘라서 번호로 바꾼다.

    first_sentences 는 body 의 앞부분을 그대로 돌려주고 split_sentences 와 같은 규칙으로
    끊으므로, 발췌의 문장 수가 곧 앞에서부터의 번호다.
    """
    excerpt = first_sentences(body, DEFAULT_SENTENCES, DEFAULT_MAX_CHARS)
    return list(range(1, len(split_sentences(excerpt)) + 1))


def parse_selection(text: str, sentence_count: int) -> list[int] | None:
    """B 의 응답에서 번호를 꺼낸다. 규칙을 어기면 None.

    **고쳐 쓰지 않고 버린다.** 범위를 벗어난 번호를 잘라내거나 5개를 4개로 줄여주면
    모델이 규칙을 얼마나 어기는지가 안 보인다. 운영에서는 None 이면 A 로 대체한다.
    """
    match = _JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        selected = json.loads(match.group(0)).get("selected")
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(selected, list):
        return None
    # bool 은 int 의 하위형이라 True 가 1 로 통과한다. 따로 막는다.
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in selected):
        return None
    unique = sorted(set(selected))
    if len(unique) > MAX_SELECT or any(n < 1 or n > sentence_count for n in unique):
        return None
    return unique


def _user_message(stock: str, title: str | None, sentences: list[str]) -> str:
    return f"종목: {stock}\n제목: {title or '(없음)'}\n\n문장:\n{numbered(sentences)}"


async def method_b(stock: str, title: str | None, sentences: list[str], body: str) -> dict:
    """문장 번호 선택. 규칙 위반이면 A 로 대체하고, 호출 실패면 error 만 남긴다."""
    result = {"selected": None, "fallback": False, "raw": "", "error": None, "cost": 0.0,
              "prompt_tokens": 0, "completion_tokens": 0}
    try:
        text, usage = await complete(load_prompt(SELECT_PROMPT),
                                     _user_message(stock, title, sentences),
                                     max_tokens=SELECT_MAX_TOKENS)
        result["raw"] = text
        result["cost"] = cost_usd(usage)
        result["prompt_tokens"] = usage.get("prompt_tokens", 0)
        result["completion_tokens"] = usage.get("completion_tokens", 0)
        result["selected"] = parse_selection(text, len(sentences))
    except LLMError as exc:
        # 호출 실패는 규칙 위반이 아니다. 모델이 아무것도 안 봤으니 B 의 결과로 셀 수 없다.
        # run 이 error 가 남은 쌍을 다시 돌리고, score 는 남아 있으면 멈춘다.
        result["error"] = str(exc)
        return result
    if result["selected"] is None:
        result["selected"] = method_a(body)
        result["fallback"] = True
    return result


async def method_c(stock: str, title: str | None, sentences: list[str], body: str) -> dict:
    """생성 요약. 숫자는 애널리스트 요약과 같은 검사기로 본문과 대조한다.

    숫자 검사는 **숫자만** 잡는다. "한 연구원" 을 "증권가" 로 부풀리는 것 같은 왜곡은
    못 잡는다. 그건 review.csv 에서 사람이 본다.
    """
    result = {"text": "", "error": None, "cost": 0.0, "prompt_tokens": 0,
              "completion_tokens": 0, "unsupported_numbers": []}
    try:
        text, usage = await complete(load_prompt(SUMMARY_PROMPT),
                                     _user_message(stock, title, sentences),
                                     max_tokens=SUMMARY_MAX_TOKENS)
        result["text"] = text
        result["cost"] = cost_usd(usage)
        result["prompt_tokens"] = usage.get("prompt_tokens", 0)
        result["completion_tokens"] = usage.get("completion_tokens", 0)
        result["unsupported_numbers"] = hallucinated_numbers(text, body)
    except LLMError as exc:
        result["error"] = str(exc)
    return result


def selected_text(sentences: list[str], indices: list[int]) -> str:
    """번호 → 원문 문장. 코드가 꺼내므로 모델이 한 글자도 바꿀 수 없다."""
    return " ".join(sentences[i - 1] for i in indices)
