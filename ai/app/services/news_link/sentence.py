"""문장을 세는 규칙. **여기 한 곳에만 둔다.**

프로토타입에서 점검 도구가 이 규칙을 따로 갖고 있었더니, "Sept. 17" 과
"T. Rowe Price" 에서 끊어 3문장짜리 발췌를 6문장으로 세고 있지도 않은 문제를
보고했다. 자르는 쪽과 세는 쪽이 같은 함수를 봐야 한다.
"""

import re

# 문장 끝. 소수점("$1.56")과 약어("U.S." "Sept.")에서 끊기지 않게 막는다.
SENT_END_RE = re.compile(r"(?<!\d)[.!?][\"'”’)\]]*(?=\s|$)")
ABBREV_TAIL_RE = re.compile(
    r"(?:\b[A-Z]|\b(?:Mr|Mrs|Ms|Dr|Prof|Inc|Corp|Co|Ltd|Jr|Sr|St|vs|No"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec))\.$"
)


def sentence_ends(body: str) -> list[int]:
    """문장이 끝나는 지점들."""
    ends = []
    for match in SENT_END_RE.finditer(body):
        if ABBREV_TAIL_RE.search(body[: match.end()]):
            continue  # "U.S." "Sept." 는 문장 끝이 아니다
        ends.append(match.end())
    # 문단 경계도 문장 끝으로 친다. 마침표 없이 끝나는 소제목("1. 유가")에서
    # 안 끊으면 세 문장이 본문 절반을 삼킨다.
    ends += [match.start() for match in re.finditer(r"\n", body)]
    return sorted({end for end in ends if end > 0})


def split_sentences(body: str) -> list[str]:
    """본문을 문장 단위로 나눈다. sentence_ends 와 같은 규칙을 쓴다."""
    out: list[str] = []
    prev = 0
    for end in [*sentence_ends(body), len(body)]:
        chunk = body[prev:end].strip()
        if chunk:
            out.append(chunk)
        prev = end
    return out


def first_sentences(body: str, count: int, max_chars: int) -> str:
    """본문 앞 count 문장을 잘라낸다.

    반환값은 **언제나 body 의 앞부분 그대로**다. 요약도 재구성도 하지 않는다.
    나중에 붙일 인용 대조가 그 성질에 기대게 된다.

    앞부분만 싣는 것은 payload 때문이다. 본문 전량을 실으면 프로토타입 실측으로
    종목당 5,000 토큰이 35,000 토큰이 됐다. 3문장이면 15건에 약 1,900 토큰이다.
    """
    ends = sentence_ends(body)
    cut = ends[count - 1] if len(ends) >= count else len(body)
    if cut > max_chars:  # 문장이 길면 상한 안쪽 경계로 되돌린다
        fits = [end for end in ends if end <= max_chars]
        cut = fits[-1] if fits else max_chars
    return body[:cut].strip()
