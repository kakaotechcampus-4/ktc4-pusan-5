"""quote 대조(verify.quote_in_text). 원문과 quote 양쪽에 같은 정규화(공백, 괄호 속 영문·숫자 약어)를
걸고, 원문의 "말(약어)" 는 quote 가 "말(약어)"·"말"·"약어" 어느 꼴로 써도 맞는다.

실패 사례는 2026-10-06 ~ 10-15 러너 실행에서 나온 QUOTE_NOT_IN_SOURCE 를 quote 기준으로 겹치지 않게
모은 것이다(재시도 1건 포함, 11건). 원문은 그 url 메시지 text 에서 quote 주변을 그대로 잘라 왔다.
그 밖의 유사도 비교는 없다 — 단어를 바꾸거나 빼거나 더한 quote 는 그대로 떨어져야 한다.
"""

import pytest

from app.services.stock_analysis.repair import quote_failures
from app.services.stock_analysis.verify import normalize_quote, quote_in_text

URL = "https://t.me/ch/1"


def failures(text: str, quote: str) -> list[str]:
    factor = {"sources": [{"url": URL, "quote": quote}]}
    return quote_failures(factor, [{"url": URL, "text": text}], "factors[0]")


# (사례, 원문 메시지 일부, 실패한 quote, 지금 규칙으로 통과하나).
# 원문 "인공지능(AI)" 를 "AI" 로 옮긴 세 건만 통과한다. 나머지는 단어를 바꾸거나 빼거나 더했다.
OBSERVED = [
    ("LG에너지솔루션-10-06 단어 바꿈",
     "이는 지난해 같은 기간 대비 2% 줄어든 수치이지만, 월가 전망치였던 46만1천대는 뛰어넘는 실적을 내면서",
     "시장 예상치였던 46만1천대는 뛰어넘는 실적", False),
    ("SK하이닉스-10-07 줄 건너 합침",
     "외인\n\n\n매수 > 삼성전기(0.16조) 삼성SDI(0.1조)\n\n\n매도 > SK하이닉스(1.4조) 삼성전자(0.56조)",
     "외인 매도 > SK하이닉스(1.4조)", False),
    ("SK하이닉스-10-08 종목명·어미 바꿈",
     "삼성전자와 SK하이닉스는 “데이터센터 분야에서 우리의 야심찬 목표를 달성하는 데 매우 중요하다”고 밝힘",
     "삼성과 SK하이닉스는 “데이터센터 분야에서 우리의 야심찬 목표를 달성하는 데 매우 중요하다”고 밝혀", False),
    ("삼성전자-10-08 인공지능(AI) → AI",
     "삼성전자와 SK하이닉스 주요 관계자들을 만나 인공지능(AI) 반도체 협력 확대 방안을 논의한다.",
     "AI 반도체 협력 확대 방안을 논의한다.", True),
    ("LG에너지솔루션-10-13 어구 바꿈",
     "LG에너지솔루션과 엘앤에프가 이달 중 다년간 최대 수십만톤 규모의 LFP 양극재 공급 계약을 맺는다.",
     "다년간 최대 수십만톤 규모의 LFP 양극재 공급계약 체결 예정", False),
    ("LG에너지솔루션-10-13 중간 어구를 뺌(국산 소재)",
     "LG엔솔은 국산 소재를 확보해 미국의 외국우려기업(PFE) 규제 속에서 북미 ESS 시장 경쟁력을 강화하려는 포석이다.",
     "국산 소재를 확보해 북미 ESS 시장 경쟁력을 강화하려는 포석", False),
    ("삼성전자-10-13 인공지능(AI) → AI",
     "립부 탄 인텔 최고경영자(CEO)와 혹 탄 브로드컴 CEO가 인공지능(AI) 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음.",
     "AI 산업의 최대 리스크로 자본조달 비용을 거론", True),
    ("삼성전자-10-13 재시도",
     "립부 탄 인텔 최고경영자(CEO)와 혹 탄 브로드컴 CEO가 인공지능(AI) 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음.",
     "AI 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음", True),
    ("LG에너지솔루션-10-14 조사 더함",
     "3) 미국의 전력망 보안 행정명령은 BESS를 규제 대상 장비로 명시\n\n\n\n\n4) 중국산 제품에 대한",
     "미국의 전력망 보안 행정명령은 BESS를 규제 대상으로 장비로 명시", False),
    ("SK하이닉스-10-14 단어 뺌",
     "• SK하이닉스 HBM4 관련 후공정 장비 물량 일부가 당초 올 하반기에서 내년으로 연기될 가능성 제기",
     "HBM4 후공정 장비 물량 일부가 당초 올 하반기에서 내년으로 연기될 가능성 제기", False),
    ("LG에너지솔루션-10-14 중간 어구를 뺌",
     "중국산 일반 하이브리드 및 플러그인 하이브리드 차량의 대EU 수출을 제한하는 데 원칙적으로 합의했다며",
     "중국산 하이브리드 차량의 대EU 수출을 제한", False),
]


@pytest.mark.parametrize(("case", "text", "quote", "passes"), OBSERVED, ids=[c[0] for c in OBSERVED])
def test_observed_failures_under_current_rule(case, text, quote, passes):
    assert (not failures(text, quote)) is passes, case


def test_made_up_phrase_still_fails():
    """원문에 없는 말을 섞은 quote. "(PFE)" 를 어느 꼴로 읽어도 "미국의 외국우려기업 규제 속에서" 가 빠져 있다."""
    text = "LG엔솔은 국산 소재를 확보해 미국의 외국우려기업(PFE) 규제 속에서 북미 ESS 시장 경쟁력을 강화하려는 포석이다."
    assert failures(text, "국산 소재를 확보해 북미 ESS 시장 경쟁력을 강화하려는 포석")
    for ok in ("국산 소재를 확보해 미국의 외국우려기업 규제 속에서",
               "국산 소재를 확보해 미국의 PFE 규제 속에서",
               "국산 소재를 확보해 미국의 외국우려기업(PFE) 규제 속에서"):
        assert not failures(text, ok), ok


SOURCE = "립부 탄 인텔 최고경영자(CEO)와 혹 탄 브로드컴 CEO가 인공지능 (AI) 산업의 최대 리스크로 거론했다."


@pytest.mark.parametrize("quote", [
    "인공지능(AI) 산업의 최대 리스크로",   # 원문 그대로
    "인공지능 산업의 최대 리스크로",       # 말
    "AI 산업의 최대 리스크로",             # 약어
    "CEO가 AI 산업의",                    # 말(약어) 앞 낱말과 이어서
    "인텔 CEO와 혹 탄 브로드컴 CEO가 인공지능 산업",  # 두 "말(약어)" 를 서로 다른 꼴로
    "고경영자와 혹 탄",                    # 말 중간에서 시작
    "능 산업의",
])
def test_word_abbreviation_matches_all_three_forms(quote):
    assert quote_in_text(quote, SOURCE), quote


@pytest.mark.parametrize("quote", [
    "인공지능AI 산업의",            # 두 꼴을 이어 붙인 것은 원문 어느 꼴과도 다르다
    "AI(인공지능) 산업의",          # 순서를 뒤집은 것
    "인공 산업의",                  # 말을 줄인 것
    "A 산업의",
    "브로드컴 CEO가 AI산업의",      # 띄어쓰기를 지운 것
])
def test_other_variants_of_word_abbreviation_fail(quote):
    assert not quote_in_text(quote, SOURCE), quote


def test_abbreviation_on_quote_side_only_is_ignored():
    assert not failures("전방 공정 장비 수요가 늘었다", "전방 공정(FE) 장비 수요가 늘었다")


def test_standalone_abbreviation_without_word_is_dropped():
    """앞에 말이 없는 괄호 약어(구두점 뒤)는 괄호째 지운다."""
    assert quote_in_text("발표했다. 매출은", "발표했다. (AI) 매출은")
    assert not quote_in_text("발표했다. AI 매출은", "발표했다. (AI) 매출은")


@pytest.mark.parametrize(("text", "kept"), [
    ("SK하이닉스(1.4조)", "SK하이닉스(1.4조)"),  # 한글이 섞이면 약어가 아니다
    ("항목(2) 참고", "항목(2) 참고"),            # 숫자뿐이면 번호다
    ("연도(2026) 기준", "연도(2026) 기준"),
    ("인공지능(AI) 산업", "인공지능 산업"),
    ("후공정(BE)과 전공정(FE)", "후공정과 전공정"),
    ("인공지능 (AI) 산업", "인공지능 산업"),
    ("고대역폭메모리(HBM4) 공급", "고대역폭메모리 공급"),
    ("긴 괄호(ABCDEFGHIJK) 는 둔다", "긴 괄호(ABCDEFGHIJK) 는 둔다"),
])
def test_normalize_quote_targets_short_ascii_abbreviations_only(text, kept):
    assert normalize_quote(text) == kept


def test_numbers_in_parens_are_not_abbreviations():
    """"(2)" 는 약어가 아니라 말(약어) 꼴로 읽지 않는다. 숫자를 빼고 옮기면 떨어진다."""
    assert not quote_in_text("항목 참고", "항목(2) 참고")
    assert not quote_in_text("2 참고", "항목(2) 참고")


def test_quote_of_only_an_abbreviation_is_empty_and_fails():
    assert failures("인공지능(AI) 산업", "(AI)")
