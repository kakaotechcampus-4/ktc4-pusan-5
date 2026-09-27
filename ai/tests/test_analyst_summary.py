"""요약 검증. LLM 을 부르지 않는다 — 채점 로직만 본다.

실제로 모델이 냈던 나쁜 출력을 픽스처로 박아둔다. 이 검증이 느슨해지면
없는 숫자가 들어간 요약이 조용히 DB 에 쌓인다.
"""

from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError
from app.services.analyst import summary as summary_service
from app.services.analyst.summary import (
    MAX_CHARS,
    MIN_CHARS,
    build_facts,
    clean,
    grade,
    hallucinated_numbers,
    is_repeated,
    stated_goal_price,
)

BODY = (
    "오리온에 대해 투자의견 매수와 목표주가 180,000원을 제시한다.\n"
    "3분기 매출액은 7,821억원으로 전년 대비 12% 증가했다. "
    "중국 법인 매출이 약 3천억원을 기록하며 회복세를 보였다.\n"
    "2026년 영업이익률은 17.2% 수준을 유지할 전망이다."
)


def test_clean_strips_markdown() -> None:
    """요약은 DB 에 그대로 들어가고 화면에도 그대로 나간다. 마크다운이 섞이면 안 된다."""
    assert clean("**오리온, 중국 회복**\n\n본문") == "오리온, 중국 회복\n\n본문"
    assert clean("## 제목\n본문") == "제목\n본문"


def test_hallucinated_numbers_flags_invented_figure() -> None:
    """모델이 재무제표에서 단위를 환산해 내놓은 적이 있다. 본문에 없는 숫자를 잡는다."""
    assert hallucinated_numbers("매출 4,535억원을 기록했다", BODY) == ["4,535"]


def test_hallucinated_numbers_allows_body_figures() -> None:
    assert hallucinated_numbers("매출액 7,821억원, 영업이익률 17.2%", BODY) == []


def test_hallucinated_numbers_ignores_years() -> None:
    """연도는 본문에 없어도 환각이 아니다."""
    assert hallucinated_numbers("2027년에도 성장할 전망이다", BODY) == []


def test_hallucinated_numbers_matches_korean_units() -> None:
    """본문 '약 3천억원' 과 요약 '3,000억원' 은 같은 값이다.

    이걸 모르면 오탐이 난다 — 실제로 전력망 리포트에서 7,000 을 환각으로 잡았다.
    """
    assert hallucinated_numbers("중국 매출 3,000억원", BODY) == []


@pytest.mark.parametrize(
    ("summary", "body", "bad"),
    [
        ("영업이익률 99.9%", "영업이익률 17.2%", ["99.9"]),
        ("매출 99억원", "매출 12억원", ["99"]),
        ("매출 1,234억원", "매출 12,345억원", ["1,234"]),
        ("매출 1,234억원", "재무표 12 34억원", ["1,234"]),
        ("매출 300억원", "매출 300백만원", ["300"]),
        ("매출 7,000억원", "수주 7천만원", ["7,000"]),
        ("성장률 12%", "성장률 12%p", ["12"]),
        ("성장률 -12%", "성장률 12%", ["-12"]),
        ("매출 453.5억원", "재무표\n십억원\n453.5", ["453.5"]),
        ("시장 규모 3,000억원", "시장 규모 약 3천억원", []),
        ("목표주가 180,000원", "목표주가 18만원", []),
        ("매출 12.5억원", "매출 12.5억원", []),
        ("성장률 12%", "성장률 12퍼센트", []),
        ("성장률 12%p", "성장률 12퍼센트포인트", []),
        ("매출 100달러", "매출 $100", []),
        ("매출 300억원, 이익 20억원", "매출 300억원, 이익 20억원", []),
        ("이익 215억원", "이익 215억 원", []),
        ("8,300억원을 투자", "8,300억을 투자", []),
        ("3분기와 4분기", "3Q, 4Q26 실적", []),
        ("3Q26 실적", "2026년 3분기 실적", []),
        ("9월 30일 상장", "상장예정일 2026.09.30", []),
        ("성장률 18.1%", "각각 9.7%,18.1% 증가", []),
        ("점수 1.71 개선", "점수 1.71로 감소", []),
        ("PER 4.18배", "PER 4.18x", []),
        ("성능 1.8배", "성능 x1.8", []),
        ("현재주가 36,150원", "현재주가36,150원상승여력33%", []),
        ("영업이익 193% 증가", "상반기영업이익YoY193%증가", []),
        ("선정 기업은 16개다", "선정기업16개다", []),
        ("비용 2000원", "비용 1000원", ["2000"]),
        ("성장률 2000%", "성장률 1000%", ["2000"]),
    ],
)
def test_hallucinated_numbers_checks_complete_values_and_units(summary, body, bad):
    assert hallucinated_numbers(summary, body) == bad


@pytest.mark.asyncio
async def test_generate_accumulates_usage_and_sends_validation_feedback(monkeypatch):
    good = "실적 개선 전망\n\n" + "가" * MIN_CHARS + "다."
    complete = AsyncMock(side_effect=[
        ("짧은 요약", {"prompt_tokens": 100, "completion_tokens": 20,
                    "cost": 0.01, "completion_tokens_details": {"reasoning_tokens": 10}}),
        (good, {"prompt_tokens": 200, "completion_tokens": 30,
                "cost": 0.02, "completion_tokens_details": {"reasoning_tokens": 15}}),
    ])
    monkeypatch.setattr(summary_service, "complete", complete)
    text, usage, result = await summary_service.generate("분석 본문", "산업.pdf")
    assert text == good
    assert result["ok"] and result["attempt"] == 2
    assert usage["prompt_tokens"] == 300
    assert usage["completion_tokens"] == 50
    assert usage["completion_tokens_details"]["reasoning_tokens"] == 25
    assert usage["cost"] == pytest.approx(0.03)
    first_user = complete.call_args_list[0].args[1]
    retry_user = complete.call_args_list[1].args[1]
    assert "이전 응답 검증 결과" not in first_user
    assert "이전 응답 검증 결과" in retry_user
    assert "길이 5자" in retry_user


@pytest.mark.asyncio
async def test_generate_preserves_usage_after_final_error(monkeypatch):
    complete = AsyncMock(side_effect=[
        ("짧은 요약", {"prompt_tokens": 100, "completion_tokens": 20}),
        LLMError("연결 실패"),
    ])
    monkeypatch.setattr(summary_service, "complete", complete)
    text, usage, result = await summary_service.generate("분석 본문", "산업.pdf", attempts=2)
    assert text == ""
    assert usage == {"prompt_tokens": 100, "completion_tokens": 20}
    assert not result["ok"] and result["attempt"] == 2
    assert result["problems"] == ["연결 실패"]


@pytest.mark.asyncio
async def test_generate_retries_token_limit_finish_and_keeps_usage(monkeypatch):
    good = "실적 개선 전망\n\n" + "가" * MIN_CHARS + "다."
    complete = AsyncMock(side_effect=[
        (good, {"completion_tokens": 8000, "finish_reason": "length"}),
        (good, {"completion_tokens": 1000, "finish_reason": "stop"}),
    ])
    monkeypatch.setattr(summary_service, "complete", complete)
    _, usage, result = await summary_service.generate("분석 본문", "산업.pdf")
    assert result["ok"] and result["attempt"] == 2
    assert usage["completion_tokens"] == 9000
    assert usage["finish_reason"] == "stop"
    assert "출력 토큰 한도 도달" in complete.call_args_list[1].args[1]


def test_is_repeated_detects_duplicate_summary() -> None:
    """모델이 같은 요약을 통째로 두 번 쓰는 경우가 있었다."""
    once = (
        "오리온은 중국 법인 매출 회복과 원가 안정에 힘입어 하반기 실적이 "
        "개선될 것으로 판단한다. 투자의견 매수를 유지한다."
    )
    assert not is_repeated(once)
    assert is_repeated(once + "\n\n" + once)


def test_stated_goal_price() -> None:
    assert stated_goal_price("목표주가 180,000원을 제시했다") == 180_000
    assert stated_goal_price("목표주가 18만원을 제시했다") == 180_000
    assert stated_goal_price("투자의견 매수를 유지한다") is None


def test_grade_passes_clean_summary() -> None:
    """정상 요약은 통과해야 한다. 검증이 과하면 멀쩡한 것도 재생성하게 된다."""
    summary = (
        "오리온, 중국 회복이 이끄는 실적 개선\n\n"
        "하나증권은 오리온에 대해 투자의견 매수와 목표주가 180,000원을 제시했다. "
        "3분기 매출액은 7,821억원으로 전년 대비 12% 증가하며 시장 기대치를 웃돌았다. "
        "부진했던 중국 법인이 약 3천억원 매출로 회복세에 접어든 점이 실적을 이끌었다.\n\n"
        "원가 부담이 완화되면서 2026년 영업이익률은 17.2% 수준을 유지할 전망이다. "
        "제품 가격 인상 효과가 온전히 반영되는 시점이 하반기라는 점에서 "
        "이익 개선 폭은 분기를 거듭할수록 커질 것으로 보인다.\n\n"
        "다만 중국 소비 경기가 다시 꺾일 경우 회복 속도가 둔화될 수 있다. "
        "현지 채널별 판매 추이와 경쟁사 가격 정책을 계속 확인할 필요가 있다는 판단이다."
    )
    assert MIN_CHARS <= len(summary) <= MAX_CHARS, len(summary)
    result = grade(summary, BODY, expect_goal=180_000)
    assert result["ok"], result["problems"]


def test_grade_catches_goal_price_mismatch() -> None:
    """모델이 '직전 목표주가' 를 집은 경우다. 규칙이 뽑은 값을 믿는다.

    네이버 정답 40건 대조에서 규칙이 100% 였다.
    """
    summary = "목표주가 340,000원을 제시했다. " * 20
    result = grade(summary[:MAX_CHARS], BODY, expect_goal=180_000)
    assert any("목표주가 불일치" in p for p in result["problems"])


def test_grade_catches_missing_goal_price() -> None:
    """종목 리포트인데 목표주가가 없으면 읽는 사람이 원문을 열지 정할 수 없다."""
    summary = "중국 법인 매출이 회복세를 보이고 있다는 판단이다. " * 15
    result = grade(summary[:MAX_CHARS], BODY, expect_goal=180_000)
    assert "목표주가 누락" in result["problems"]


def test_grade_rejects_unconfirmed_goal_even_if_number_is_in_body() -> None:
    result = grade("목표주가 18만원을 제시했다.", "주가 180,000원", expect_goal=None)
    assert "확인되지 않은 목표주가" in result["problems"]


def test_grade_checks_later_conflicting_goal_prices() -> None:
    result = grade("목표주가 180,000원. 목표주가 340,000원.", BODY, expect_goal=180_000)
    assert any("목표주가 불일치" in problem for problem in result["problems"])


def test_grade_accepts_verified_goal_with_unit_in_table_header() -> None:
    summary = "목표주가 180,000원\n\n" + "가" * MIN_CHARS + "다."
    result = grade(summary, "목표주가(원) 180,000", expect_goal=180_000)
    assert result["ok"], result["problems"]


@pytest.mark.parametrize("summary", [
    "목표주가 31,000원. 기존 목표주가 35,000원에서 하향했다.",
    "목표주가 31,000원. 목표주가는 기존 35,000원에서 하향했다.",
    "목표주가를 기존 35,000원에서 31,000원으로 하향했다.",
    "목표주가 31,000원. 직전 목표주가 35,000원에서 하향했다.",
    "목표주가 31,000원. 목표주가는 상향 조정됐으며, 현재주가 20,000원이다.",
])
def test_grade_distinguishes_current_goal_from_previous_goal_and_price(summary):
    assert stated_goal_price(summary) == 31_000
    result = grade(summary, "31,000원 35,000원 20,000원", expect_goal=31_000)
    assert not any("목표주가 불일치" in problem for problem in result["problems"])


@pytest.mark.parametrize("ending", ["문제는 기업", "권역책임의료기관 사업은 경쟁"])
def test_grade_detects_unfinished_last_sentence(ending):
    result = grade("완성된 앞부분. " + "가" * MIN_CHARS + ending, BODY)
    assert "문장 미완료" in result["problems"]


def test_grade_catches_leaked_notes() -> None:
    """생각 과정이 새어 나온 경우."""
    summary = "오리온 실적 개선\n\n- \"중국 매출 확인\"\n" + "본문. " * 60
    result = grade(summary[:MAX_CHARS], BODY)
    assert "작업 노트 유출" in result["problems"]


@pytest.mark.parametrize("length", [MIN_CHARS - 50, MAX_CHARS + 50])
def test_grade_catches_bad_length(length: int) -> None:
    """네이버 요약 474건 분포로 잡은 범위다. 너무 짧으면 쓸모없고 길면 요약이 아니다."""
    result = grade("가" * length, BODY)
    assert any("길이" in p for p in result["problems"])


def test_build_facts_gives_goal_price_for_company_report() -> None:
    """종목 리포트는 목표주가·투자의견을 확정값으로 주입한다."""
    facts, goal = build_facts("오리온［271560］_20260914.pdf", BODY)
    assert goal == 180_000
    assert "투자의견: 매수" in facts
    assert "목표주가: 180,000원" in facts


def test_build_facts_omits_goal_price_for_industry_report() -> None:
    """산업 리포트는 종목이 여러 개라 하나를 고르면 거짓이 된다.

    item_code 를 비우는 것과 같은 이유다.
    """
    body = (
        "은행 업종에 대해 Overweight 의견을 유지한다. Top picks: KB금융\n"
        "KB금융(105560) 신한지주(055550) 하나금융지주(086790)\n"
        "목표주가 120,000원\n" + "본문 " * 200
    )
    facts, goal = build_facts("산업_은행_한화투자증권_260914.pdf", body)
    assert goal is None
    assert "종목별 목표주가를 쓰지 않는다" in facts
    assert "업종의견: 비중확대" in facts


def test_grade_rejects_unsubstantiated_sector_view():
    summary = "업종의견 '중립'을 제시했다. " + "원문의 기후 변화 대응 전략을 설명한다. " * 22
    result = grade(summary, "탄소중립을 최종 목표가 아닌 새로운 성장 기회로 본다.")
    assert "업종의견 불일치" in result["problems"]


def test_grade_rejects_invented_overweight_from_credit_outlook():
    summary = "크레딧 시장에 대해 비중확대 의견을 유지했다. " + "신용 스프레드의 강세를 전망한다. " * 24
    result = grade(summary, "신용 스프레드 소폭 강세를 전망하며 분할매수 접근이 유효하다.")
    assert "확인되지 않은 투자의견" in result["problems"]
