"""기사 본문에서 기사가 아닌 것을 걷어낸다. extract.py 가 import 해서 쓴다.

왜 따로 떼어냈나. 프로토타입에서 확보한 본문 22건을 훑어보니 **9건(41%)에 기사가
아닌 것이 섞여 있었다.** 앞 3문장만 싣는데 그중 한두 칸을 이런 것이 차지한다.

    ft.com                   "Save now on essential digital access… Then ₩79999 per month."
    counterpointresearch.com "Counterpoint Research는 …리서치 기업입니다"
    techpowerup.com          "Thursday, September 17th 2026" / 제목 한 줄
    yna.co.kr                "(서울=연합뉴스) 이도흔 기자 = " 뒤에야 본문이 시작된다

어느 매체가 언제 썼는지는 이미 `domain` 과 메시지 게시 시각에 있다. 본문에서 또
받을 이유가 없고, 3문장 중 한 칸을 내줄 값어치는 더더욱 없다.

**규칙은 두 가지만 쓴다. 지우거나, 앞머리를 떼거나.** 문장을 다시 쓰거나 중간을
이어붙이지 않는다. 남는 글자가 원문 그대로여야 나중에 모델의 인용을 원문과 문자열로
대조할 수 있다. 문단을 통째로 빼고 앞머리를 떼는 것은 남는 글자를 건드리지 않으므로
그 성질이 유지된다.

**머리 규칙(lead)은 본문 첫 문장을 만나기 전까지만 적용한다.** 기사 중간의 소제목까지
지우면 떨어져 있던 문장이 붙어서, 원문에 없던 흐름이 만들어진다.

backend 의 `services/news/clean.py` 와 목적이 다르다. 그쪽은 LLM 요약에 넣을 입력을
만드느라 공백을 합치고 3000자에서 자른다. 여기는 인용 대조를 살리려고 남는 글자를
한 자도 바꾸지 않는다. 두 소스를 한 정제기로 합치는 문제는 아직 팀 논의 중이다.
"""

import re

# 문장이 끝났다고 볼 표시. 한국어 기사는 "…다." "…습니다." 로 끝난다.
# **중국어·일본어 마침표(。)를 빠뜨리면 안 된다.** 처음에 빠뜨렸더니 udn.com 의
# 멀쩡한 중국어 문단 두 개가 "종결부호 없는 짧은 줄" 로 몰려 부제 취급을 받았다.
SENT_TAIL_RE = re.compile(
    r"[.!?。！？][\"'”’)\]」』）】]*$"  # 종결부호로 끝난다 (닫는 따옴표·괄호까지 허용)
    r"|"
    r"[다요음임함]\.?$"  # 마침표를 안 찍는 한국어 기사체 ("…라고 밝혔다")
)

# (이름, 설명, 적용범위, 정규식)
#   범위 "any"     어디서든 그 문단을 버린다
#   범위 "lead"    **본문 첫 문장을 만나기 전까지만** 버린다
DROP_RULES: list[tuple[str, str, str, str]] = [
    ("copyright", "저작권·재배포 안내", "any",
     r"무단\s*전재|저작권자|재배포\s*금지|Copyright\s*©|All rights reserved"),
    ("subscribe", "구독·제보 안내", "any",
     r"구독하기|구독\s*신청|제보는|앱\s*다운|뉴스레터|Subscribe to|Sign up for"),
    ("paywall", "유료 구독 광고", "any",
     (r"Save now on|per month|per year|cancel anytime|무료\s*체험|"
      r"디지털\s*구독|Then\s*[₩$€£]")),
    ("aisummary", "AI 자동요약 안내", "any",
     r"자동\s*생성한\s*요약|AI가\s*자동\s*생성|AI\s*핵심\s*요약"),
    ("promo", "매체 홍보·공유 버튼", "any",
     r"다음뉴스|네이버에서\s|기사\s*공유|선호\s*출처로\s*추가|많이\s*본\s*뉴스"),
    ("about", "회사 소개문 (기사가 아님)", "any",
     r"리서치\s*기업입니다|리서치를\s*모두\s*제공|About\s+us\b|회사\s*소개"),
    ("blocked", "자바스크립트·광고차단 안내", "any",
     r"enable\s+JS|ad\s?block|Please enable|브라우저를\s*업데이트"),
    ("caption", "사진 설명·광고 자리", "any",
     r"^(이미지\s*확대|사진\s*=|\[사진|AD|▲)"),
    ("section", "기사 중간 소제목", "any", r"^[◆■▶●▣※]\s*"),
    # 이메일이 들어 있는 짧은 줄은 본문 문장이 아니라 서명이다. "기자" 라는 낱말에
    # 기대면 "YTN 권영희 (kwonyh@ytn.co.kr)" 처럼 직함 없는 서명을 놓친다.
    ("contact", "기자 서명·연락처 줄", "any",
     r"^(?=.{0,70}$).*[\w.\-]+@[\w.\-]+\.\w{2,}"),
    ("dateline", "작성·수정 시각", "lead",
     (r"^((Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day|"
      r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d|"
      r"\d{4}[.\-년]\s?\d{1,2}|기사입력|최종수정|입력\s*\d{4})")),
]

# 앞머리만 떼어낸다. 뒤에 남는 문장은 한 글자도 건드리지 않는다.
TRIM_RULES: list[tuple[str, str, str]] = [
    ("byline_paren", "(서울=연합뉴스) OOO 기자 =",
     r"^\([^)]{1,24}\)\s*\S{1,12}\s*(기자|특파원)\s*=\s*"),
    ("byline_bracket", "[서울=뉴스핌] OOO 기자 =",
     r"^\[[^\]]{1,24}\]\s*\S{1,12}\s*(기자|특파원)\s*=\s*"),
    ("byline_inline", "[더바이오 OOO 기자]", r"^\[[^\]]{1,30}(기자|특파원)\]\s*"),
    ("headmark", "[단독] [속보] 같은 머리표", r"^\[(단독|속보|종합|르포|인터뷰|기획)\d?\]\s*"),
]

DROP_RE = [(n, why, scope, re.compile(p, re.IGNORECASE)) for n, why, scope, p in DROP_RULES]
TRIM_RE = [(n, why, re.compile(p)) for n, why, p in TRIM_RULES]

# 머리에서 지울 짧은 비문장. 제목·부제가 여기 걸린다.
# 종결부호가 없다는 것이 강한 신호다 — 기사 문장은 "다." 나 "." 로 끝난다.
SUBHEAD_MAX = 120


def looks_like_sentence(text: str) -> bool:
    return bool(SENT_TAIL_RE.search(text.strip()))


def clean_paragraphs(
    paragraphs: list[str], title: str | None = None
) -> tuple[list[str], list[tuple[str, str]]]:
    """문단 목록을 정제한다. (남은 문단, [(규칙이름, 지운 것)]) 를 돌려준다.

    지우거나 앞머리를 떼는 것만 한다. 남는 글자는 원문 그대로다.
    지운 내역을 함께 돌려주는 것은 규칙을 손볼 때 무엇이 사라졌는지 봐야 하기 때문이다.
    """
    kept: list[str] = []
    log: list[tuple[str, str]] = []
    in_lead = True  # 아직 본문 첫 문장을 못 만났다
    normalized_title = re.sub(r"\s+", "", title or "")

    for paragraph in paragraphs:
        text = paragraph.strip()
        if not text:
            continue

        hit = None
        for name, _why, scope, pattern in DROP_RE:
            if scope == "lead" and not in_lead:
                continue
            if pattern.search(text):
                hit = name
                break
        if hit:
            log.append((hit, text))
            continue

        if in_lead:
            # 제목을 본문에 한 번 더 싣는 매체가 있다. 제목은 이미 title 에 있다.
            if (
                normalized_title
                and len(normalized_title) > 10
                and re.sub(r"\s+", "", text) in normalized_title
            ):
                log.append(("title_echo", text))
                continue
            # 종결부호 없는 짧은 줄 = 제목이거나 부제다.
            if not looks_like_sentence(text) and len(text) <= SUBHEAD_MAX:
                log.append(("subhead", text))
                continue

        for name, _why, pattern in TRIM_RE:
            match = pattern.match(text)
            if match:
                log.append((name, match.group(0)))
                text = text[match.end() :].strip()
        if not text:
            continue

        if looks_like_sentence(text):
            in_lead = False  # 여기부터는 본문이다
        kept.append(text)

    return kept, log
