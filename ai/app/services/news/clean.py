"""raw_text → cleaned_text.

순서가 중요하다. 꼬리말과 번역본을 먼저 걷어낸 뒤 길이 상한을 건다.
상한을 먼저 걸면 본문은 잘리고 잡음만 남을 수 있다.
"""

import re

MAX_CHARS = 3000  # LLM 요약 입력 상한. 브리핑 담당과 조율 후 바꾼다
_MIN_HANGUL_RATIO = 0.3  # 문단의 한글 비율이 이 밑이면 번역본·영문 인용으로 본다

# 1층: 이 줄만 지운다. 기자 바이라인은 본문 앞에 오는 매체(한경 등)도 있어서 뒤를 자르면 안 된다
_DROP_LINE_RE = re.compile(
    r"^\s*("
    r".*기자\s*[\w.+-]+@"  # 홍길동 기자 abc@ / 홍길동 한경닷컴 기자 abc@
    r"|/?\s*[가-힣]{2,4}\s*기자\s*$"  # /김재옥기자
    r"|[\w.+-]+@[\w-]+\.[\w.]+\s*$"  # 이메일만 있는 줄
    r"|.*\([\w.+-]+@[\w.-]+\)\s*$"  # YTN 윤태인 (abc@ytn.co.kr)
    r"|(영상|촬영|편집|그래픽|자료조사)[가-힣]*\s*[:：]"  # 방송사 제작진 표기
    r"|.*제보는\s*카카오톡"  # 연합뉴스 꼬리
    r"|.*\d{2}시\d{2}분\s*송고\s*$"
    r"|관련\s*(뉴스|기사)\s*$"
    r"|AD\s*$"
    r"|\d{4}-\d{2}-\d{2}\s+[A-Z]?\d+면\s*$"  # 서울신문 지면 표기
    r")",
)

# 2층: 이 줄부터 끝까지 버린다. 본문이 끝났다는 확실한 표시만 둔다
_TAIL_RE = re.compile(
    r"^\s*("
    r".*무단\s*전재"
    r"|.*재배포\s*금지"
    r"|.*Copyright"
    r"|.*ⓒ"
    r"|.*저작권자"
    r"|.*제보하기"  # KBS ■ 제보하기
    r"|.*당신의 제보가"  # YTN
    r"|.*이 기사가 좋으셨다면"  # KBS
    r"|.*구독해주세요"
    r"|\[카카오톡\]"
    r")",
    re.MULTILINE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HANGUL_RE = re.compile(r"[가-힣]")
_ALPHA_RE = re.compile(r"[A-Za-zÀ-ÿ가-힣]")


def _strip_tail(text: str) -> str:
    m = _TAIL_RE.search(text)
    if m and m.start() > 200:  # 앞 200자 안에서 걸리면 오탐으로 보고 자르지 않는다
        text = text[: m.start()]
    return "\n".join(line for line in text.split("\n") if not _DROP_LINE_RE.match(line))


def _cut_foreign(text: str) -> str:
    """한글 비율이 떨어지는 문단부터 뒤를 버린다. 벤처스퀘어처럼 영·불 번역이 붙는 경우 대응.

    본문이 아직 충분히 쌓이기 전(한글 200자 미만)에는 자르지 않고 그 문단만 건너뛴다.
    앞머리에 링크·영문 헤더가 오는 사이트에서 전체를 잃지 않기 위해서다.
    """
    kept: list[str] = []
    hangul_so_far = 0
    for para in text.split("\n"):
        letters = _ALPHA_RE.findall(para)
        hangul = len(_HANGUL_RE.findall(para))
        if len(letters) >= 20 and hangul / len(letters) < _MIN_HANGUL_RATIO:
            if hangul_so_far >= 200:
                break
            continue
        kept.append(para)
        hangul_so_far += hangul
    return "\n".join(kept)


def clean_text(raw: str, *, max_chars: int = MAX_CHARS) -> str:
    text = _HTML_TAG_RE.sub("", raw).replace("\xa0", " ")  # 일부 사이트는 태그째 나온다
    text = _strip_tail(text)
    text = _cut_foreign(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:max_chars]
