"""기사에서 종목이 움직인 원인이 담긴 문장을 **번호로** 고른다.

    from app.services.news_link import fetch_link_bodies, select_sentences

    bodies = await fetch_link_bodies(urls)                  # 링크당 한 번. LLM 을 안 부른다
    picked = await select_sentences("삼성전자", bodies[0])  # (링크, 종목)마다 한 번

모델은 번호만 낸다. 문장은 코드가 원문에서 그대로 꺼내므로 모델이 한 글자도 바꿀 수 없다.
요약을 새로 쓰게 하면 "~라는 풀이가 나온다" 가 "~이다" 로 단정되는 식의 변형이 생기는데,
검사기로 그걸 다 잡지 못했다. 번호 선택은 그런 변형이 구조적으로 생기지 않는다.

기사가 이 종목을 다루지 않으면 모델이 빈 목록을 낸다(status "none"). 발췌와 함께
"이 기사가 이 종목 이야기인가" 판단을 겸한다. 종목명이 한두 번 스친 기사(고객사로 언급,
다른 업종 리포트에 이름만 나옴)는 문자열 검색으로 거를 수 없다.

방식은 PR #34 의 비교 실험(기사 31건, 앞 3문장·번호 선택·생성 요약)으로 정했다.
번호 선택은 원인을 일부라도 담은 것이 25/25, 원인 없는 기사를 비운 것이 5/6 이었다.
약점은 필요한 문장을 빠뜨리는 것(전부 담은 것 13/25)과 고른 문장만으로 뜻이 안 통하는
것(20/26)이다.
"""

import hashlib
import json
import logging
import re

from app.llm.client import PROMPT_DIR, LLMError, complete, load_prompt
from app.services.news_link.schema import LinkBody, LinkSelection, SelectionStatus
from app.services.news_link.sentence import split_sentences

logger = logging.getLogger(__name__)

PROMPT_NAME = "news_select"

# 모델이 고를 수 있는 최대 문장 수. 앞 3문장보다 한 칸 더 준다 — 가리키는 말("이 회사는")의
# 대상 문장을 함께 고르라고 시키기 때문이다. 하한은 없다. 원인 없는 기사는 0개가 정답이다.
MAX_SELECT = 4

# 출력 토큰 상한. 출력은 {"selected": [...]} 한 줄(~20토큰)이다. 설정 기본값
# (summary_max_tokens=8000)은 애널리스트 요약이 추론 모델에 맞춰 잡은 값이고, Elice 는
# 6000 을 넘으면 400 으로 거절한다(2026-09-25 실측). 추론 토큰도 출력으로 과금되니 여유만 둔다.
SELECT_MAX_TOKENS = 1000

_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)

# 앞 내용을 받는 말. 이 말로 시작하는 문장은 앞 문장이 있어야 뜻이 선다.
# 모델에게도 "가리키는 대상을 함께 고르라" 고 시키지만 혼자 고르는 일이 있어서 코드가 채운다.
# 규칙이면 매번 같은 결과가 나온다.
# 못 잡는 것: 앞에서 정의한 낱말만 쓰는 문장("'Muse' 가 …"), 대명사로 시작하는 문장("그는 …").
BACK_REFERENCE_OPENERS = (
    "따라서", "이에", "이처럼", "이는", "이를", "이후",
    "이 회사", "이 같은", "이같은", "같은 ", "해당 ",
)
# 역접은 붙이지 않는다. 실험에서 모델이 고른 역접 문장 4건 중 3건은 앞 문장이 필요 없었고,
# 붙였더니 뜻이 오히려 흐려지기도 했다(PR #34 리뷰).
#   가온전선  "다만 시장에서는 … 투자심리가 자극된 것으로 풀이된다"  ← 붙은 앞 문장 "별다른 공시는 없었다"
# 역접 뒤에 앞 내용을 받는 말이 이어지면 그 말 때문에 붙인다: "그러나 이후 오름폭은 축소됐다".
CONTRAST_OPENERS = ("다만", "반면", "하지만", "그러나")
_LEADING_MARKS = "\"'“‘([ "


def needs_previous(sentence: str) -> bool:
    """앞 문장이 있어야 뜻이 서는 문장인가."""
    text = sentence.lstrip(_LEADING_MARKS)
    for opener in CONTRAST_OPENERS:
        if text.startswith(opener):
            # 역접만으로는 붙이지 않는다. 바로 뒤에 오는 말을 본다.
            text = text[len(opener) :].lstrip(" ,")
            break
    return text.startswith(BACK_REFERENCE_OPENERS)


def with_context(sentences: list[str], indices: list[int]) -> list[int]:
    """앞 내용을 받는 문장이면 바로 앞 문장을 붙인다. 한 칸만 붙이고 거슬러 올라가지 않는다.

    거슬러 올라가면 "이에 …" "이는 …" 이 이어지는 분석 기사에서 문단 전체가 딸려 온다.
    """
    out = set(indices)
    for i in indices:
        if i > 1 and needs_previous(sentences[i - 1]):
            out.add(i - 1)
    return sorted(out)


def parse_selection(text: str, sentence_count: int) -> list[int] | None:
    """응답에서 번호를 꺼낸다. 규칙을 어기면 None.

    **고쳐 쓰지 않고 버린다.** 범위를 벗어난 번호를 잘라내거나 5개를 4개로 줄여주면
    모델이 규칙을 얼마나 어기는지가 안 보인다. None 이면 앞 3문장으로 대체한다.
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


def numbered(sentences: list[str]) -> str:
    """모델과 사람이 **같은 번호**를 보게 한다."""
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))


def user_message(stock: str, title: str | None, sentences: list[str]) -> str:
    return f"종목: {stock}\n제목: {title or '(없음)'}\n\n문장:\n{numbered(sentences)}"


def selected_text(sentences: list[str], indices: list[int]) -> str:
    """번호 → 원문 문장. 코드가 꺼내므로 모델이 한 글자도 바꿀 수 없다."""
    return " ".join(sentences[i - 1] for i in indices)


def prompt_sha256() -> str:
    """프롬프트 **파일 바이트**의 해시. 어느 판의 프롬프트로 고른 발췌인지 가린다.

    load_prompt() 의 반환값이 아니라 파일을 해시한다. load_prompt 는 앞뒤 공백을 걷어내서,
    파일을 열어 sha256sum 한 값과 맞춰 볼 수 없게 된다.
    """
    return hashlib.sha256((PROMPT_DIR / f"{PROMPT_NAME}.md").read_bytes()).hexdigest()


def _lead(
    result: LinkSelection, link: LinkBody, status: SelectionStatus, error: str | None = None
) -> LinkSelection:
    """앞 3문장(fetch 가 만든 excerpt)으로 대체한다. 번호 선택을 붙이기 전과 같은 발췌다."""
    result.status = status
    result.error = error
    result.excerpt = link.excerpt
    result.indices = list(range(1, len(split_sentences(link.excerpt)) + 1)) if link.excerpt else []
    return result


async def select_sentences(stock: str, link: LinkBody) -> LinkSelection:
    """(기사, 종목) 한 쌍의 발췌. 호출 실패는 예외로 올리지 않는다.

    링크 하나에 종목이 여럿이면 종목마다 부른다. 본문은 fetch_link 가 열어 둔 것을 쓴다.

    설정이 빠진 것(RuntimeError)은 그대로 올린다. 키가 없는데 조용히 앞 3문장으로
    대체하면 모든 링크가 대체된 채로 끝나고, 그게 설정 탓이라는 게 안 보인다.
    """
    result = LinkSelection(url=link.url, stock=stock, status="no_body")
    sentences = link.sentences
    if not sentences:
        return result

    result.prompt_sha256 = prompt_sha256()
    try:
        text, usage = await complete(
            load_prompt(PROMPT_NAME),
            user_message(stock, link.title, sentences),
            max_tokens=SELECT_MAX_TOKENS,
        )
    except LLMError as exc:
        logger.warning("문장 선택 실패 (%s, %s): %s", stock, link.url, exc)
        return _lead(result, link, "error", error=str(exc))

    result.raw = text
    result.usage = usage
    picked = parse_selection(text, len(sentences))
    if picked is None:
        return _lead(result, link, "fallback")
    if not picked:
        # 앞 3문장으로 대체하지 않는다. 대체하면 "이 종목 기사가 아니다" 는 판단이 사라진다.
        result.status = "none"
        return result
    result.status = "selected"
    result.model_indices = picked
    result.indices = with_context(sentences, picked)
    result.excerpt = selected_text(sentences, result.indices)
    return result
