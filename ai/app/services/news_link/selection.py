"""기사에서 종목이 움직인 원인이 담긴 문장을 **번호로** 고른다.

    from app.services.news_link import fetch_link_bodies, select_sentences

    bodies = await fetch_link_bodies(urls)                  # 링크당 한 번. LLM 을 안 부른다
    picked = await select_sentences("삼성전자", bodies[0])  # (링크, 종목)마다 LLM 을 한 번 부른다

모델은 문장 번호만 낸다. 문장은 코드가 원문에서 그대로 꺼내므로 모델이 한 글자도 바꿀 수 없다.
모델에게 요약을 새로 쓰게 했더니 "~라는 풀이가 나온다" 가 "~이다" 로 단정되는 식으로 뜻이
바뀌었고, 규칙 검사기를 붙여도 다 잡지 못했다. 번호로 고르게 하면 이런 변형이 생길 수 없다.

기사가 이 종목을 다루지 않으면 모델이 빈 목록을 낸다(status "none"). 그래서 발췌를 하면서
"이 기사가 이 종목 이야기인가" 도 함께 판단한다. 이 판단은 기사에 종목명이 있는지 문자열로
찾아서는 할 수 없다. 고객사로 한 번 언급되거나 다른 업종 리포트에 이름만 스친 기사에도
종목명은 들어 있기 때문이다.

이 방식은 PR #34 의 비교 실험으로 정했다. 기사 31건에 앞 3문장·번호 선택·생성 요약을 돌려
비교했고, 번호 선택의 결과는 이렇다.
    - 원인이 있는 기사 25건 중 원인을 일부라도 담은 것 25건, 빠짐없이 담은 것 13건
    - 원인이 없는 기사 6건 중 빈 목록을 낸 것 5건
    - 문장을 고른 기사 26건 중 고른 문장만 읽어도 뜻이 통한 것 20건
약점은 두 가지다. 필요한 문장을 빠뜨릴 때가 있고(25건 중 12건), 고른 문장만으로는 뜻이
안 통할 때가 있다(26건 중 6건). 뒤의 것을 줄이려고 with_context() 가 앞 문장을 붙인다.

앞의 것을 줄이려고 프롬프트에 "원인이 두 문장에 걸쳐 있을 때" 규칙을 넣고 "적을수록 좋다" 를
뺐다. 같은 31건을 보강 전·후 프롬프트로 두 번씩 돌린 결과다(2026-10-03, 같은 모델).
    - 빠짐없이 담음 15·16/25 → 17·16/25, 평균 정밀도(고른 문장 중 정답 비율) 58·56% → 53·55%
    - 상한을 5개로 늘리면 빠짐없이 담음은 17·17/25 로 거의 그대로인데 정밀도가 48·45% 로
      떨어져서 4개로 둔다
    - "그는", 'Muse' 처럼 몇 문장 앞에서 소개한 대상을 가리키는 경우(3건)는 프롬프트로도 못 잡았다
같은 프롬프트도 돌릴 때마다 1건 안팎씩 달라진다. 보강 효과(평균 1건)는 그 폭과 비슷하다.
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

# 모델이 고를 수 있는 최대 문장 수. 기본 발췌(앞 3문장)보다 하나 많다. 고른 문장에 "이 회사는"
# 처럼 앞을 가리키는 말이 있으면 그 대상 문장도 함께 고르라고 시키기 때문이다(news_select.md).
# 최소 개수는 없다. 원인이 없는 기사는 0개가 정답이다. 5개로 늘려 본 결과는 맨 위 설명에 있다.
MAX_SELECT = 4

# 출력 토큰 상한. 답은 {"selected": [...]} 한 줄이라 20토큰 안팎이지만, 추론 모델은 생각하는 데
# 쓴 토큰도 출력으로 세고 과금하므로 그만큼 여유를 둔다. 추론이 이 상한을 넘으면 답이 빈 채로
# 와서 fallback(앞 3문장)이 된다.
# 설정 기본값(summary_max_tokens=8000)은 애널리스트 요약에 맞춘 값이라 여기에는 너무 크고,
# Elice 는 6000 을 넘으면 400 으로 거절한다(2026-09-25 실측).
SELECT_MAX_TOKENS = 1000

# 응답에서 처음 나오는 {...} 하나. 모델이 코드 블록(```json)이나 설명을 덧붙여도 JSON 만 꺼낸다.
_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)

# 앞 문장을 받는 말. 이 말로 시작하는 문장은 앞 문장이 있어야 뜻이 통한다.
# 프롬프트에서도 "가리키는 대상 문장을 함께 고르라" 고 시키지만, 모델이 그 문장만 고르고
# 앞 문장을 빠뜨릴 때가 있어서 코드가 채운다. 코드 규칙은 매번 같은 결과를 낸다.
# 못 잡는 것: 앞에서 정의한 낱말만 쓰는 문장("'Muse' 가 …"), 대명사로 시작하는 문장("그는 …").
BACK_REFERENCE_OPENERS = (
    "따라서", "이에", "이처럼", "이는", "이를", "이후",
    "이 회사", "이 같은", "이같은", "같은 ", "해당 ",
)
# 역접("다만", "하지만" 등)으로 시작한다는 이유만으로는 앞 문장을 붙이지 않는다. 실험에서 모델이
# 고른 역접 문장 4건 중 3건은 앞 문장 없이도 뜻이 통했고, 붙였더니 뜻이 오히려 흐려진 경우도
# 있었다(PR #34 리뷰).
#   예) 가온전선 기사에서 "다만 시장에서는 … 투자심리가 자극된 것으로 풀이된다" 를 골랐을 때
#       앞 문장 "별다른 공시는 없었다" 를 붙였더니 뜻이 오히려 흐려졌다.
# 역접 바로 뒤에 앞 문장을 받는 말이 오면 그 말 때문에 붙인다. 예) "그러나 이후 오름폭은 축소됐다"
CONTRAST_OPENERS = ("다만", "반면", "하지만", "그러나")
# 문장 앞의 따옴표·괄호·공백. 이걸 걷어낸 뒤에 여는 말을 본다(따옴표로 시작하는 인용문 때문).
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
    """앞 문장을 받는 문장이면 바로 앞 문장의 번호를 더해서, 정렬된 번호 목록을 돌려준다.

    번호는 1부터 센다(모델에게 보여준 [1] [2] 와 같다). 한 칸만 붙이고 더 거슬러 올라가지 않는다.
    거슬러 올라가면 "이에 …" "이는 …" 이 이어지는 분석 기사에서 문단 전체가 딸려 온다.
    """
    out = set(indices)
    for i in indices:
        if i > 1 and needs_previous(sentences[i - 1]):
            out.add(i - 1)
    return sorted(out)


def parse_selection(text: str, sentence_count: int) -> list[int] | None:
    """응답에서 번호 목록을 꺼낸다. 돌려주는 값은 셋 중 하나다.

        [3, 5]  정상. 정렬하고 중복을 뺀 번호
        []      정상. "이 기사는 이 종목을 다루지 않는다" 는 답이다 (status "none")
        None    규칙 위반. JSON 이 없거나, selected 가 정수 목록이 아니거나, 1~sentence_count
                밖의 번호가 있거나, MAX_SELECT 개보다 많다. 부르는 쪽이 앞 3문장으로 대체한다

    **규칙을 어긴 응답은 고쳐 쓰지 않고 버린다.** 범위를 벗어난 번호를 잘라내거나 5개를
    4개로 줄여주면 모델이 규칙을 얼마나 어기는지가 안 보인다. 중복을 하나로 합치는 것만 한다.
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
    """문장마다 [1] [2] … 번호를 붙여 한 줄씩 늘어놓는다.

    모델이 이 번호로 고르고, CLI(__main__.show_selection)도 같은 번호로 결과를 보여준다.
    그래서 모델의 답과 사람이 보는 화면을 바로 맞춰 볼 수 있다.
    """
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))


def user_message(stock: str, title: str | None, sentences: list[str]) -> str:
    """모델에 보내는 질문. 종목 → 제목 → 번호 붙인 문장 순서다. 지시문은 news_select.md 에 있다."""
    return f"종목: {stock}\n제목: {title or '(없음)'}\n\n문장:\n{numbered(sentences)}"


def selected_text(sentences: list[str], indices: list[int]) -> str:
    """번호에 해당하는 원문 문장을 공백 하나로 잇는다. 코드가 꺼내므로 모델이 글자를 바꿀 수 없다."""
    return " ".join(sentences[i - 1] for i in indices)


def prompt_sha256() -> str:
    """프롬프트 **파일 바이트**의 sha256. 결과가 어느 버전의 프롬프트로 나왔는지 가린다.

    load_prompt() 의 반환값이 아니라 파일 자체를 해시한다. load_prompt 는 앞뒤 공백을 걷어내서,
    그 값을 해시하면 터미널에서 sha256sum 으로 구한 파일 해시와 달라진다.
    """
    return hashlib.sha256((PROMPT_DIR / f"{PROMPT_NAME}.md").read_bytes()).hexdigest()


def _lead(
    result: LinkSelection, link: LinkBody, status: SelectionStatus, error: str | None = None
) -> LinkSelection:
    """문장 선택이 실패했을 때(error·fallback) 기사 앞 3문장으로 대체한다.

    lead 는 기사 첫머리라는 뜻이다. 발췌는 fetch_link 가 만든 excerpt 를 그대로 쓰므로,
    문장 선택을 붙이기 전과 같은 결과가 된다.
    """
    result.status = status
    result.error = error
    result.excerpt = link.excerpt
    result.indices = list(range(1, len(split_sentences(link.excerpt)) + 1)) if link.excerpt else []
    return result


async def select_sentences(stock: str, link: LinkBody) -> LinkSelection:
    """(기사, 종목) 한 쌍의 발췌. LLM 호출이 실패해도 예외를 올리지 않고 status 에 남긴다.

    링크 하나에 종목이 여럿이면 종목마다 부른다. 결과 status 는 selected·none·fallback·
    error·no_body 중 하나다(schema.py 의 SelectionStatus).

    문장은 fetch_link 가 채워 둔 link.sentences 에서 고른다. sentences 는 JSON 으로 저장되지
    않으므로, 파일에서 다시 읽은 LinkBody 를 넘기면 언제나 no_body 가 된다. 링크를 연 같은
    실행 안에서 불러야 한다.

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
