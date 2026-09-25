"""생성 요약(C)을 원문과 대조하는 규칙 검사. LLM 을 부르지 않는다.

C 는 모델이 문장을 새로 쓰므로 지어낼 수 있다. 파일럿·텔레그램 31건을 사람이 채점해 보니
통째로 지어낸 것은 없었지만 아래가 나왔다. 규칙으로 잡을 수 있는 것만 여기 둔다.

    numbers      원문(제목 포함)에 없는 숫자                     analyst 요약과 같은 검사기
    not_korean   요약이 한국어가 아니다                          중국어 기사를 중국어로 요약했다
    hedge        원문의 조심 표현(풀이·전망·관측…)이 빠졌다      "전략이란 풀이가 나온다" → "전략이다"
    ungrounded   요약 문장의 글자 조각이 원문에 별로 없다         근거가 약한 문장
    stock_absent 종목이 기사에 안 나오는데 요약을 썼다            '관련 내용 없음' 을 써야 했다

**못 잡는 것**: "한 연구원" 을 "증권가" 로 넓히는 식의 뜻 왜곡. 낱말이 원문과 거의 같아서
글자 비교로는 안 보인다. 이건 사람이 보거나, LLM 에게 한 번 더 검증시켜야 한다(비용 발생).

**외국어 기사는 hedge·ungrounded 를 건너뛴다.** 원문이 영어·중국어고 요약이 한국어면
글자 조각이 겹칠 수가 없어서 전부 걸린다. 걸리는 게 전부면 검사가 아니다.
"""

import re

from app.services.analyst.summary import hallucinated_numbers
from app.services.news_link.sentence import split_sentences

# 원문에서 볼 것: **추측·해석** 표현. 이게 있는 문장은 사실이 아니라 누군가의 해석이다.
# "업계에 따르면" "관계자는 … 말했다" 같은 **출처** 표현은 넣지 않았다. 처음에 넣었더니
# 42건 중 10건이 걸렸는데 거의 전부 멀쩡했다 — 사실 보도의 출처는 요약에서 빠져도 된다.
SPECULATIVE = (
    "풀이", "관측", "추정", "해석", "전망", "예상", "가능성",
    "것으로 보", "보인다", "알려졌", "알려진", "파악됐", "분석이",
)
# 요약에서 볼 것: 조심 표현이 **어느 것이든** 하나 있으면 살렸다고 본다. 표현을 바꿔 쓰는
# 것까지 막으면 멀쩡한 요약이 걸린다("해석이 확산됐다" → "수 있음을 주시했다").
CAREFUL = (
    *SPECULATIVE, "분석", "평가", "기대", "우려", "검토", "예정", "계획", "수 있", "시장에서는",
    "따르면", "밝혔", "말했", "전했", "설명했", "강조했", "주장", "관계자",
)

# 요약이 한국어인가. 글자(한글·한자·가나·로마자) 중 한글이 이만큼은 돼야 한다.
# 한국어 요약에도 영문 회사명·단위가 섞이므로 절반으로 잡았다.
MIN_HANGUL_RATIO = 0.5
# 원문이 한국어인가. 이보다 낮으면 외국어 기사로 보고 글자 대조 검사를 건너뛴다.
KOREAN_SOURCE_RATIO = 0.3
# 요약 문장의 글자 두 개 조각 중 원문에 있는 비율. 이보다 낮으면 근거가 약하다고 본다.
# 텔레그램 20건의 멀쩡한 요약 문장은 대부분 0.8 이상이었다.
MIN_GROUNDED_RATIO = 0.6

_LETTER_RE = re.compile(r"[가-힣]|[一-鿿]|[぀-ヿ]|[A-Za-z]")
_HANGUL_RE = re.compile(r"[가-힣]")
_KEEP_RE = re.compile(r"[가-힣一-鿿A-Za-z0-9]")


def hangul_ratio(text: str) -> float:
    letters = _LETTER_RE.findall(text)
    return len(_HANGUL_RE.findall(text)) / len(letters) if letters else 0.0


def bigrams(text: str) -> set[str]:
    """띄어쓰기·문장부호를 걷어내고 두 글자씩 자른다. 한국어는 조사가 붙어도 앞 조각이 남는다."""
    chars = "".join(_KEEP_RE.findall(text))
    return {chars[i : i + 2] for i in range(len(chars) - 1)}


def grounded_ratio(sentence: str, source_grams: set[str]) -> float:
    grams = bigrams(sentence)
    return len(grams & source_grams) / len(grams) if grams else 1.0


def closest_source(sentence: str, source_sentences: list[str]) -> str:
    """요약 문장과 글자 조각이 가장 많이 겹치는 원문 문장."""
    grams = bigrams(sentence)
    return max(source_sentences, key=lambda s: len(grams & bigrams(s)), default="")


def is_speculative(text: str) -> bool:
    return any(h in text for h in SPECULATIVE)


def is_careful(text: str) -> bool:
    return any(h in text for h in CAREFUL)


def verify_summary(summary: str, stock: str, title: str | None, body: str) -> list[str]:
    """걸린 항목을 사람이 읽을 문장으로 돌려준다. 빈 목록이면 규칙상 문제없음.

    '관련 내용 없음' 요약은 stock_absent 반대 방향만 본다(종목이 기사에 있는데 없다고 함).
    """
    source = f"{title or ''}\n{body}"
    text = summary.strip()
    flags: list[str] = []

    if text.strip(". ") == "관련 내용 없음":
        if stock and stock in source:
            flags.append(f"stock_present: 기사에 '{stock}' 이 나오는데 관련 내용 없음이라고 함")
        return flags

    if stock and hangul_ratio(source) >= KOREAN_SOURCE_RATIO and stock not in source:
        flags.append(f"stock_absent: 기사에 '{stock}' 이 없는데 요약을 씀")

    foreign = hangul_ratio(source) < KOREAN_SOURCE_RATIO
    numbers = hallucinated_numbers(text, source)
    if numbers:
        # 외국어 원문은 번역하면서 표기가 바뀐다("six quarters" → "6개 분기"). 걸려도 참고만 한다.
        tag = "numbers(참고·번역)" if foreign else "numbers"
        flags.append(f"{tag}: 원문에 없는 숫자 {', '.join(numbers)}")

    if hangul_ratio(text) < MIN_HANGUL_RATIO:
        flags.append(f"not_korean: 한글 비율 {hangul_ratio(text):.0%}")

    if foreign:
        return flags  # 외국어 원문 — 글자 대조 검사는 의미가 없다

    source_sentences = split_sentences(body)
    source_grams = bigrams(source)
    for sentence in split_sentences(text):
        ratio = grounded_ratio(sentence, source_grams)
        if ratio < MIN_GROUNDED_RATIO:
            flags.append(f"ungrounded: 원문 대조 {ratio:.0%} — {sentence[:60]}")
            continue
        origin = closest_source(sentence, source_sentences)
        if is_speculative(origin) and not is_careful(sentence):
            flags.append(f"hedge: 원문 '{origin[:50]}' → 요약 '{sentence[:50]}'")
    return flags
