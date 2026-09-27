"""텔레그램 리포트 요약 생성.

네이버는 API 가 요약을 준다(5종 100/100 확인). 텔레그램은 PDF 하나뿐이라
본문을 읽어서 만들어야 한다. 그래서 이 모듈은 사실상 텔레그램 전용이다.

## 왜 검증이 붙어 있나

팀 규칙이 "모든 금융 수치는 결정론적 Python 코드가 생성한다. LLM 은 추론·종합·설명만"
이다. 요약은 설명이라 LLM 이 맞는데, 그 안에 숫자가 섞여 들어온다. 그래서 두 가지를 한다.

    ① 투자의견·목표주가는 **규칙이 뽑아서 확정값으로 주입한다.** 모델이 본문에서
       다시 찾지 않게 한다. 규칙은 네이버 정답 40건 대조 100% 다.
    ② 생성된 요약의 숫자를 본문과 대조한다. 본문에 없는 숫자가 있으면 다시 생성한다.

②가 필요한 이유는 실제로 겪어서다. 모델이 재무제표에서 453.5(십억원)를 읽고
4,535억원으로 환산해 내놨다. 계산은 맞는데 표에서 끌어온 값이라 항목이 어긋나 있었다.
"""

import logging
import re
from decimal import Decimal

from app.llm.client import LLMError, complete, load_prompt
from app.services.analyst.telegram import (
    classify,
    find_goal_price,
    find_opinion,
    find_sector_view,
)

logger = logging.getLogger(__name__)

PROMPT_NAME = "analyst_summary"
# 네이버 요약 474건의 길이 분포를 보고 잡았다. 중앙값 517자, 90퍼센타일 900자다.
# 처음에 900 을 상한으로 뒀다가 네이버 자신도 19% 가 넘는 걸 보고 넓혔다.
MIN_CHARS, MAX_CHARS = 350, 900
MAX_ATTEMPTS = 3

_YEAR = re.compile(r"^(19|20)\d\d$")
_NUMBER = re.compile(
    r"(?<!\d)(?<!\d[.,])(?P<number>[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?!\d|[.,]\d)"
)
_UNIT = re.compile(
    r"[ \t]*(?P<scale>[십백천만억조]*)[ \t]*(?P<unit>"
    r"퍼센트포인트|퍼센트|%[pP]|%|[bB][pP][sS]?|달러|유로|원|엔|위안|"
    r"분기|개월|년|월|일|시간|[hH][rR]|배(?!당|경|치|부|분)|[xX]|주(?!가|요|목)|"
    r"명(?!시|확|백)|개(?!선|발|편|별|입)|건(?!설|강)|대(?!비|상|응|표|로)|"
    r"톤|[tT][bB]|[gG][bB]|[mM][bB])?"
)
_SCALE = {"십": 10, "백": 100, "천": 1000, "만": 10_000,
          "억": 100_000_000, "조": 1_000_000_000_000}
_UNIT_ALIASES = {"퍼센트": "%", "퍼센트포인트": "%p", "bps": "bp", "x": "배", "hr": "시간"}
_QUARTER = re.compile(r"(?<!\d)([1-4])\s*[Qq](?:[’']?(?:20)?\d{2}[EF]?)?")
_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])"
    r"(?:\s*[./-]\s*(0?[1-9]|[12]\d|3[01]))?(?!\d)"
)
# 요약은 DB 에 그대로 들어가고 화면에도 그대로 나간다. 마크다운 기호가 섞이면 안 된다.
# 첫 줄에 **강조**를 붙여 내보내는 경우가 실제로 있었다.
_MARKDOWN = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|^#{1,6}\s*", re.MULTILINE)
_LEAKED_NOTES = re.compile(r"->|→\s*(대부분|확인|발견)|^\s*-\s*\"", re.MULTILINE)
_GOAL_IN_TEXT = re.compile(
    r"(?:목표\s*주가|목표가)\s*(?:[은는을를:]\s*)?"
    r"(?P<previous>기존|직전|종전)?\s*"
    r"(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<man>만)?\s*원"
)
_GOAL_CHANGE_TO = re.compile(
    r"\s*(?:에서|→|->)\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(만)?\s*원"
)


def clean(text: str) -> str:
    """마크다운 기호를 걷고 빈 줄을 정리한다."""
    text = _MARKDOWN.sub(lambda m: m.group(1) or m.group(2) or "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _number_tokens(text: str) -> list[tuple[str, Decimal, str]]:
    """숫자 경계를 보존하고, 숫자 바로 뒤에 명시된 단위만 읽는다.

    PDF 표의 서로 다른 칸 '12 34' 를 1234로 합치지 않는다. '3천억원'과
    '3,000억원'처럼 명시적인 규모 표기는 맞추되 표 머리의 단위를 추측하지 않는다.
    """
    tokens = []
    periods = list(_QUARTER.finditer(text)) + list(_DATE.finditer(text))
    for period in periods:
        if period.re is _QUARTER:
            tokens.append((period.group(1), Decimal(period.group(1)), "분기"))
        else:
            tokens.append((period.group(2), Decimal(period.group(2)), "월"))
            if period.group(3):
                tokens.append((period.group(3), Decimal(period.group(3)), "일"))
    for match in _NUMBER.finditer(text):
        if any(start.start() <= match.start() < start.end() for start in periods):
            continue
        raw = match.group("number")
        value = Decimal(raw.replace(",", "").replace("−", "-"))
        suffix = _UNIT.match(text, match.end())
        scale = suffix.group("scale") if suffix else ""
        unit = (suffix.group("unit") or "").lower() if suffix else ""
        # '천억', '백만' 등의 명시적 배수. 복합 금액의 덧셈은 추측하지 않는다.
        for part in scale:
            value *= _SCALE[part]
        unit = _UNIT_ALIASES.get(unit, unit)
        # 한국어 금융 문장의 '8,300억을 투자'는 원을 생략한 표기다. 억/조도
        # 없는 맨숫자 표 셀에는 이 규칙을 적용하지 않는다.
        if not unit and any(part in scale for part in "억조"):
            unit = "원"
        if not unit and match.start() and text[match.start() - 1] in "xX":
            unit = "배"
        if not unit and match.start() and text[match.start() - 1] == "$":
            unit = "달러"
        tokens.append((raw, value, unit))
    return tokens


def hallucinated_numbers(summary: str, body: str) -> list[str]:
    """요약에는 있는데 본문에는 없는 숫자. 연도와 한글 단위 표기는 같은 값으로 친다."""
    body_values = {(value, unit) for _, value, unit in _number_tokens(body)}
    out = []
    for token, value, unit in _number_tokens(summary):
        plain = token.replace(",", "")
        if _YEAR.match(plain) and unit in {"", "년"}:
            continue
        if (value, unit) in body_values:
            continue
        # 단위를 생략한 숫자는 동일한 값이 원문에 있으면 허용한다. 요약에 단위를
        # 썼다면 단위 없는 표 셀이나 다른 단위의 숫자로 근거를 대신할 수 없다.
        if not unit and any(value == body_value for body_value, _ in body_values):
            continue
        out.append(token)
    return sorted(set(out))


def is_repeated(summary: str) -> bool:
    """같은 요약을 두 번 쓴 경우. 첫 문장이 뒤에 또 나오면 반복이다."""
    head = summary.strip()[:40]
    return len(head) >= 20 and summary.count(head) > 1


def stated_goal_price(summary: str) -> int | None:
    """요약이 실제로 쓴 목표주가."""
    goals = _stated_goal_prices(summary)
    return goals[0] if goals else None


def _stated_goal_prices(summary: str) -> list[int]:
    goals = []
    for match in _GOAL_IN_TEXT.finditer(summary or ""):
        changed = _GOAL_CHANGE_TO.match(summary, match.end())
        if changed:
            amount, man = changed.groups()
        else:
            prefix = summary[max(0, match.start() - 8):match.start()]
            if match.group("previous") or re.search(r"(?:기존|직전|종전)\s*$", prefix):
                continue
            amount, man = match.group("amount", "man")
        goals.append(int(Decimal(amount.replace(",", "")) * (10_000 if man else 1)))
    return goals


def grade(summary: str, body: str, expect_goal: int | None = None) -> dict:
    """요약을 채점한다. problems 가 비면 통과다."""
    problems: list[str] = []
    if not summary:
        problems.append("빈 응답")
    if is_repeated(summary):
        problems.append("요약 반복")
    if _LEAKED_NOTES.search(summary):
        problems.append("작업 노트 유출")
    # 목표가는 별도의 결정론적 추출기가 확인했다. '목표주가(원) 180,000'처럼
    # 원문 단위가 앞에 붙은 경우에도 이 확정 사실은 숫자의 근거로 사용할 수 있다.
    number_evidence = body + (f"\n목표주가 {expect_goal:,}원" if expect_goal else "")
    bad = hallucinated_numbers(summary, number_evidence)
    if bad:
        problems.append(f"본문에 없는 숫자 {bad}")
    if summary and not (MIN_CHARS <= len(summary) <= MAX_CHARS):
        problems.append(f"길이 {len(summary)}자")
    if summary and not re.search(r"[.!?。！？다함됨임음)\]\"'”’]$", summary.rstrip()):
        problems.append("문장 미완료")
    # 규칙이 뽑은 목표주가와 요약이 쓴 값이 다르면 모델이 '직전 목표주가'를 집은 것이다.
    # 네이버 정답 40건 대조에서 규칙이 100% 였다 — 규칙을 믿는다.
    stated = _stated_goal_prices(summary)
    said = stated[0] if stated else None
    if expect_goal:
        for wrong in sorted(set(stated) - {expect_goal}):
            problems.append(f"목표주가 불일치: 요약 {wrong:,} vs 규칙 {expect_goal:,}")
    elif stated:
        problems.append("확인되지 않은 목표주가")
    if expect_goal and summary and not said:
        problems.append("목표주가 누락")
    sector_claim = re.search(
        r"(?:업종|산업)(?:에\s*대한)?\s*(?:투자)?의견[은는을를\s:'\"‘’“”]*"
        r"(비중확대|중립|비중축소)", summary,
    )
    if sector_claim and sector_claim.group(1) != find_sector_view(body)[0]:
        problems.append("업종의견 불일치")
    # '크레딧 시장에 대해 비중확대 의견'처럼 업종이라는 단어가 없어도
    # 공식 등급을 새로 만들면 안 된다. 단순 매수 접근 제안과 등급은 구분한다.
    rating_claims = re.findall(r"(비중\s*확대|비중\s*축소|중립)\s*(?:의견|등급)", summary)
    known_ratings = {find_sector_view(body)[0], find_opinion(body)}
    if any(re.sub(r"\s", "", rating) not in known_ratings for rating in rating_claims):
        problems.append("확인되지 않은 투자의견")
    return {
        "chars": len(summary),
        "hallucinated": bad,
        "goal_stated": said,
        "problems": problems,
        "ok": not problems,
    }


def build_facts(filename: str, body: str) -> tuple[str, int | None]:
    """(확정 사실 블록, 규칙이 뽑은 목표주가).

    종목 리포트에만 목표주가·투자의견을 준다. 산업 리포트는 종목이 여러 개라
    그중 하나를 실으면 거짓이 된다 — item_code 를 비우는 것과 같은 이유다.
    실제로 반도체 업종 리포트에서 모델은 목표주가를 올바르게 뺐는데
    내 채점기가 '누락' 으로 감점한 적이 있다.
    """
    kind, _ = classify(filename, body)
    if kind == "company":
        goal = find_goal_price(body)
        opinion = find_opinion(body)
        facts = (
            "[확정 사실] — 아래 값을 그대로 쓴다. 본문에서 다시 찾지 않는다.\n"
            f"  투자의견: {opinion}\n"
            f"  목표주가: {f'{goal:,}원' if goal else '없음'}\n\n"
        )
        return facts, goal

    sector_opinion, picks = find_sector_view(body)
    facts = (
        "[확정 사실] — 이 리포트는 종목 하나가 아니라 업종·전략 리포트다.\n"
        "  종목별 목표주가를 쓰지 않는다. 여러 종목을 다루므로 하나를 고르면 거짓이 된다.\n"
        f"  업종의견: {sector_opinion or '없음'}\n"
        f"  Top picks: {', '.join(picks) if picks else '없음'}\n\n"
    )
    return facts, None


async def generate(
    body: str, filename: str, *, attempts: int = MAX_ATTEMPTS
) -> tuple[str, dict, dict]:
    """(요약, 사용량, 채점). 검증에 걸리면 다시 생성하고 마지막 결과를 돌려준다.

    통과하지 못해도 마지막 것을 돌려준다. 호출부가 `grade["ok"]` 를 보고
    저장할지 정한다 — 세 번 다 걸리는 건 대개 본문 자체가 이상한 경우다.
    """
    prompt = load_prompt(PROMPT_NAME)
    facts, expect_goal = build_facts(filename, body)
    user = f"{facts}리포트 파일명: {filename}\n\n본문:\n{body}"

    last: tuple[str, dict, dict] = ("", {}, {"problems": ["시도 없음"], "ok": False})
    total_usage: dict = {}
    feedback = ""
    for attempt in range(1, attempts + 1):
        try:
            text, usage = await complete(prompt, user + feedback)
        except LLMError as exc:
            logger.warning("%s: %d/%d 실패 — %s", filename, attempt, attempts, exc)
            last = ("", total_usage, {"problems": [str(exc)], "ok": False, "attempt": attempt})
            continue
        _accumulate_usage(total_usage, usage)
        text = clean(text)
        result = grade(text, body, expect_goal)
        if usage.get("finish_reason") == "length":
            result["problems"].append("출력 토큰 한도 도달")
            result["ok"] = False
        result["attempt"] = attempt
        last = (text, total_usage, result)
        if result["ok"]:
            break
        feedback = (
            "\n\n[이전 응답 검증 결과]\n"
            + "\n".join(f"- {problem}" for problem in result["problems"])
            + "\n위 문제를 수정해 요약 전체를 다시 작성한다. 근거가 없는 숫자는 빼고, "
            "확정 사실의 목표주가와 출력 형식을 지킨다. 검증 메모는 출력하지 않는다."
        )
        if result["hallucinated"]:
            feedback += (
                "\n수치의 출처나 단위를 확실히 맞추지 못했다. 이번 재작성에서는 "
                "확정 사실로 주어진 목표주가 외의 숫자·날짜·비율을 모두 생략하고, "
                "원문에 있는 핵심 주장과 근거, 위험 요인을 정성적으로 설명한다."
            )
        logger.info("%s: %d/%d 재생성 — %s", filename, attempt, attempts, result["problems"])
    return last


def _accumulate_usage(total: dict, usage: dict) -> None:
    """재시도에서 소비한 토큰·비용과 중첩 사용량을 모두 보존한다."""
    for key, value in usage.items():
        if isinstance(value, dict):
            previous = total.setdefault(key, {})
            if isinstance(previous, dict):
                _accumulate_usage(previous, value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value
        elif key == "finish_reason":
            total[key] = value
