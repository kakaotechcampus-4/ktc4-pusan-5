"""quote 대조 정규화(verify.normalize_quote). 원문과 quote 양쪽에 같은 정규화를 건다.

실패 사례는 2026-10-06 ~ 10-15 러너 실행에서 나온 QUOTE_NOT_IN_SOURCE 를 quote 기준으로 겹치지 않게
모은 것이다(재시도 1건 포함). 원문은 그 url 메시지 text 에서 quote 주변을 그대로 잘라 왔다.
정규화는 공백과 괄호 속 영문·숫자 약어만 다룬다 — 단어를 바꾸거나 빼거나 더한 quote 는 그대로 떨어져야 한다.
"""

import pytest

from app.services.stock_analysis.repair import quote_failures
from app.services.stock_analysis.verify import normalize_quote

URL = "https://t.me/ch/1"


def failures(text: str, quote: str) -> list[str]:
    factor = {"sources": [{"url": URL, "quote": quote}]}
    return quote_failures(factor, [{"url": URL, "text": text}], "factors[0]")


# (사례, 원문 메시지 일부, 실패한 quote). 모두 정규화 뒤에도 실패해야 한다.
OBSERVED = [
    ("LG에너지솔루션-10-06 단어 바꿈",
     "이는 지난해 같은 기간 대비 2% 줄어든 수치이지만, 월가 전망치였던 46만1천대는 뛰어넘는 실적을 내면서",
     "시장 예상치였던 46만1천대는 뛰어넘는 실적"),
    ("SK하이닉스-10-07 줄 건너 합침",
     "외인\n\n\n매수 > 삼성전기(0.16조) 삼성SDI(0.1조)\n\n\n매도 > SK하이닉스(1.4조) 삼성전자(0.56조)",
     "외인 매도 > SK하이닉스(1.4조)"),
    ("SK하이닉스-10-08 종목명·어미 바꿈",
     "삼성전자와 SK하이닉스는 “데이터센터 분야에서 우리의 야심찬 목표를 달성하는 데 매우 중요하다”고 밝힘",
     "삼성과 SK하이닉스는 “데이터센터 분야에서 우리의 야심찬 목표를 달성하는 데 매우 중요하다”고 밝혀"),
    ("삼성전자-10-08 인공지능(AI) → AI",
     "삼성전자와 SK하이닉스 주요 관계자들을 만나 인공지능(AI) 반도체 협력 확대 방안을 논의한다.",
     "AI 반도체 협력 확대 방안을 논의한다."),
    ("LG에너지솔루션-10-13 어구 바꿈",
     "LG에너지솔루션과 엘앤에프가 이달 중 다년간 최대 수십만톤 규모의 LFP 양극재 공급 계약을 맺는다.",
     "다년간 최대 수십만톤 규모의 LFP 양극재 공급계약 체결 예정"),
    ("LG에너지솔루션-10-13 중간 어구를 뺌",
     "LG엔솔은 국산 소재를 확보해 미국의 외국우려기업(PFE) 규제 속에서 북미 ESS 시장 경쟁력을 강화하려는 포석이다.",
     "국산 소재를 확보해 북미 ESS 시장 경쟁력을 강화하려는 포석"),
    ("삼성전자-10-13 인공지능(AI) → AI",
     "립부 탄 인텔 최고경영자(CEO)와 혹 탄 브로드컴 CEO가 인공지능(AI) 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음.",
     "AI 산업의 최대 리스크로 자본조달 비용을 거론"),
    ("삼성전자-10-13 재시도",
     "립부 탄 인텔 최고경영자(CEO)와 혹 탄 브로드컴 CEO가 인공지능(AI) 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음.",
     "AI 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음"),
    ("LG에너지솔루션-10-14 조사 더함",
     "3) 미국의 전력망 보안 행정명령은 BESS를 규제 대상 장비로 명시\n\n\n\n\n4) 중국산 제품에 대한",
     "미국의 전력망 보안 행정명령은 BESS를 규제 대상으로 장비로 명시"),
    ("SK하이닉스-10-14 단어 뺌",
     "• SK하이닉스 HBM4 관련 후공정 장비 물량 일부가 당초 올 하반기에서 내년으로 연기될 가능성 제기",
     "HBM4 후공정 장비 물량 일부가 당초 올 하반기에서 내년으로 연기될 가능성 제기"),
    ("LG에너지솔루션-10-14 중간 어구를 뺌",
     "중국산 일반 하이브리드 및 플러그인 하이브리드 차량의 대EU 수출을 제한하는 데 원칙적으로 합의했다며",
     "중국산 하이브리드 차량의 대EU 수출을 제한"),
]


@pytest.mark.parametrize(("case", "text", "quote"), OBSERVED, ids=[c for c, _, _ in OBSERVED])
def test_observed_failures_still_fail_after_normalization(case, text, quote):
    assert failures(text, quote), case


def test_made_up_phrase_still_fails():
    """원문에 없는 말을 섞은 quote. 괄호 약어 "(PFE)" 를 지워도 "미국의 외국우려기업 규제 속에서" 가 빠져 있다."""
    text = "LG엔솔은 국산 소재를 확보해 미국의 외국우려기업(PFE) 규제 속에서 북미 ESS 시장 경쟁력을 강화하려는 포석이다."
    assert failures(text, "국산 소재를 확보해 북미 ESS 시장 경쟁력을 강화하려는 포석")
    # 약어만 뺀 그대로 옮기면 통과한다.
    assert not failures(text, "국산 소재를 확보해 미국의 외국우려기업 규제 속에서 북미 ESS")


@pytest.mark.parametrize("quote", [
    "인공지능 산업의 최대 리스크로 자본조달 비용을 거론",   # quote 가 약어를 뺐다
    "인공지능(AI) 산업의 최대 리스크로 자본조달 비용을 거론",  # 원문 그대로
    "인공지능 (AI) 산업의 최대 리스크로",                    # 괄호 앞 공백
])
def test_abbreviation_in_parens_is_ignored_on_both_sides(quote):
    text = "혹 탄 브로드컴 CEO가 인공지능(AI) 산업의 최대 리스크로 자본조달 비용을 거론하고 나섰음."
    assert not failures(text, quote)


def test_abbreviation_on_quote_side_only_is_ignored():
    assert not failures("전방 공정 장비 수요가 늘었다", "전방 공정(FE) 장비 수요가 늘었다")


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


def test_quote_of_only_an_abbreviation_is_empty_and_fails():
    assert failures("인공지능(AI) 산업", "(AI)")
