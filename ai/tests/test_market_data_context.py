"""시장 맥락 계산. 네트워크 없이 돈다.

종목 행은 tests/fixtures/market_data/ 의 2026-10-27 실제 응답에서 고른 것이다. 비중의 분모는
보통주 전 종목(그날 829종목) 시총 합이라 fixture 일부 행으로는 실제 비중이 안 나온다. 그래서
비중·기여도 공식은 손으로 셀 수 있는 숫자로 따로 확인하고, 실제 값은 live 테스트가 본다.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.services.market_data import (
    GROUPS,
    STOCK_GROUPS,
    IndexDaily,
    StockDaily,
    build_market_context,
    context,
    groups_of,
)
from app.services.market_data.context import (
    KOSPI_FOLLOW_THRESHOLD_PP,
    common_base,
    group_relation,
    is_common,
    is_mixed,
    kospi_relation,
    mixed_still_follows,
    prev_market_cap,
)
from app.services.market_data.krx import _index_row, _stock_row

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"
DAY = date(2026, 10, 27)


def _rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["OutBlock_1"]


STOCKS = [_stock_row(r) for r in _rows("krx_stk_bydd_trd.json")]
KOSPI = next(_index_row(r) for r in _rows("krx_kospi_dd_trd.json") if r["IDX_NM"] == "코스피")


def stock(code: str, cap: int, rate: float, *, volume: int = 1000) -> StockDaily:
    return StockDaily(
        bas_dd=DAY, code=code, name=code, market="KOSPI", close=None, change=None,
        change_rate=rate, open=None, high=None, low=None, volume=volume, trade_value=None,
        market_cap=cap, listed_shares=None,
    )


def kospi(rate: float) -> IndexDaily:
    return IndexDaily(
        bas_dd=DAY, series="KOSPI", name="코스피", close=None, change=None, change_rate=rate,
        open=None, high=None, low=None, volume=None, trade_value=None, market_cap=None,
    )


# --- 코스피 비중·기여도·자기 제외 --------------------------------------------------------------


def test_weight_contribution_and_ex_self_by_hand() -> None:
    """손으로 셀 수 있는 시장. 보통주 A·B 만 분모에 들어간다.

    A 당일 110 (+10%) → 전일 100,  B 당일 300 (0%) → 전일 300,  보통주 전일 합 400
    비중 A = 100/400 = 25%,  기여도 = 10 × 0.25 = 2.5%p
    코스피 2.5% → 자기 제외 = (2.5 − 2.5) / (1 − 0.25) = 0%,  초과분 = 10 − 0 = 10%p
    """
    stocks = [
        stock("000010", 110, 10.0),
        stock("000020", 300, 0.0),
        stock("000015", 1_000_000, 50.0),  # 우선주(끝자리 5): 분모에 넣으면 비중이 0 에 가까워진다
        stock("900010", 1_000_000, -30.0),  # 외국주(9로 시작)
    ]
    ctx = build_market_context("000010", DAY, kospi(2.5), stocks, groups={}, stock_groups={})

    k = ctx.kospi
    assert ctx.status == "ok"
    assert k.common_prev_market_cap_krw == 400
    assert k.kospi_recomputed_change_rate_pct == 2.5  # (100 × 10 + 300 × 0) / 400
    assert k.kospi_weight_pct == 25.0
    assert k.kospi_contribution_pp == 2.5
    assert k.kospi_ex_self_change_rate_pct == 0.0
    assert k.excess_vs_kospi_ex_self_pp == 10.0
    assert k.excess_vs_kospi_pp == 7.5
    assert "근사" in k.weight_basis


def test_common_stock_rule() -> None:
    assert is_common("005930")
    assert not is_common("005935")  # 삼성전자우
    assert not is_common("00104K")  # CJ4우(전환)
    assert not is_common("37550L")  # DL이앤씨2우(전환)
    assert not is_common("900140")  # 엘브이엠씨홀딩스(외국주)


def test_prev_market_cap_reverses_todays_move() -> None:
    samsung = next(s for s in STOCKS if s.code == "005930")
    # 1,297,873,850,976,000 ÷ 1.0423
    assert prev_market_cap(samsung) == pytest.approx(1_297_873_850_976_000 / 1.0423)


def test_real_rows_samsung() -> None:
    ctx = build_market_context("005930", DAY, KOSPI, STOCKS)

    assert ctx.status == "ok" and ctx.status_reason is None
    assert ctx.name == "삼성전자"
    k = ctx.kospi
    assert (k.stock_change_rate_pct, k.kospi_change_rate_pct) == (4.23, 3.09)
    assert k.excess_vs_kospi_pp == 1.14  # compute_excess 그대로
    # 분모가 fixture 행만이라 비중 숫자는 실제와 다르다. 공식끼리 맞물리는지만 본다
    base, _ = common_base(STOCKS)
    weight = prev_market_cap(next(s for s in STOCKS if s.code == "005930")) / base
    assert k.kospi_weight_pct == round(weight * 100, 2)
    assert k.kospi_contribution_pp == round(4.23 * weight, 3)
    assert k.kospi_ex_self_change_rate_pct == round((3.09 - 4.23 * weight) / (1 - weight), 2)
    # 비중이 fixture 기준 48.77%(실제 28%대)라 어느 쪽이든 자기 제외 코스피로 판정한다
    assert k.kospi_basis == "kospi_ex_self"
    assert k.excess_vs_kospi_ex_self_pp == 2.23
    assert k.kospi_relation == "diverges"


def test_real_rows_kb_judged_against_kospi() -> None:
    """KB금융: 비중 fixture 기준 2.04%(실제는 더 작다) → 코스피 그대로. 0.27 − 3.09 = −2.82%p."""
    k = build_market_context("105560", DAY, KOSPI, STOCKS).kospi

    assert k.kospi_weight_pct == 2.04
    assert k.kospi_basis == "kospi"
    assert k.excess_vs_kospi_pp == -2.82
    assert k.kospi_relation == "diverges"


# --- 코스피 판정 -------------------------------------------------------------------------------

SCALE = 1_000_000  # 시총이 정수라 비중(%)을 이만큼 키워 전일 시총으로 쓴다


def _kospi_ctx(target_rate: float, kospi_rate: float, weight_pct: float, *,
               code: str = "000010", target_volume: int = 1000):
    """대상과 보합 종목 000020 둘뿐인 시장. 대상의 전일 시총 비중이 weight_pct 가 되게 맞춘다."""
    prev = round(weight_pct * SCALE)
    target = stock(code, round(prev * (1 + target_rate / 100)), target_rate, volume=target_volume)
    rest = stock("000020", round(100 * SCALE) - prev, 0.0)
    return build_market_context(code, DAY, kospi(kospi_rate), [target, rest],
                                groups={}, stock_groups={})


@pytest.mark.parametrize(("weight_pct", "shown", "basis"), [
    (10.00, 10.00, "kospi_ex_self"),  # 경계: 정확히 10% 는 자기 제외
    (9.99, 9.99, "kospi"),
    (9.996, 10.00, "kospi_ex_self"),  # 반올림한 비중(보이는 숫자)으로 가른다
])
def test_kospi_basis_by_weight(weight_pct: float, shown: float, basis: str) -> None:
    k = _kospi_ctx(0.0, 0.0, weight_pct).kospi
    assert k.kospi_weight_pct == shown
    assert k.kospi_basis == basis


# 아래 표의 경계 ±1.00 / ±1.01 은 KOSPI_FOLLOW_THRESHOLD_PP = 1.0 기준이다
@pytest.mark.parametrize(("target_rate", "kospi_rate", "weight_pct", "vs_kospi", "vs_ex_self", "relation"), [
    # 비중 9.99% → 코스피 대비로 판정. 자기 제외 초과분(1.11)은 기준을 넘어도 보지 않는다
    (2.00, 1.00, 9.99, 1.00, 1.11, "follows"),  # 경계: 정확히 +1.00%p
    (0.00, 1.00, 9.99, -1.00, -1.11, "follows"),  # 경계: 정확히 −1.00%p
    (2.01, 1.00, 9.99, 1.01, 1.12, "diverges"),
    (-0.01, 1.00, 9.99, -1.01, -1.12, "diverges"),
    # 비중 20% → 자기 제외 = (코스피 − 0.2 × 종목) / 0.8. 코스피 대비(0.8 안팎)는 보지 않는다
    (2.00, 1.200, 20.0, 0.80, 1.00, "follows"),  # 경계: 자기 제외 1.00% → +1.00%p
    (0.00, 0.800, 20.0, -0.80, -1.00, "follows"),  # 경계: −1.00%p
    (2.01, 1.202, 20.0, 0.81, 1.01, "diverges"),
    (-0.01, 0.798, 20.0, -0.81, -1.01, "diverges"),
])
def test_kospi_relation(
    target_rate: float, kospi_rate: float, weight_pct: float,
    vs_kospi: float, vs_ex_self: float, relation: str,
) -> None:
    assert KOSPI_FOLLOW_THRESHOLD_PP == 1.0
    k = _kospi_ctx(target_rate, kospi_rate, weight_pct).kospi
    assert k.excess_vs_kospi_pp == vs_kospi
    assert k.excess_vs_kospi_ex_self_pp == vs_ex_self
    assert k.kospi_relation == relation


def test_kospi_and_group_thresholds_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    """코스피 판정은 KOSPI_FOLLOW_THRESHOLD_PP, 그룹 판정은 GROUP_FOLLOW_THRESHOLD_PP 만 본다."""
    monkeypatch.setattr(context, "KOSPI_FOLLOW_THRESHOLD_PP", 0.5)
    assert kospi_relation(0.80, 1.80, 1.00) == "diverges"
    assert group_relation(0.80, 2, 1.80, 1.00) == "follows"

    monkeypatch.setattr(context, "KOSPI_FOLLOW_THRESHOLD_PP", 1.0)
    monkeypatch.setattr(context, "GROUP_FOLLOW_THRESHOLD_PP", 0.5)
    assert kospi_relation(0.80, 1.80, 1.00) == "follows"
    assert group_relation(0.80, 2, 1.80, 1.00) == "diverges"


@pytest.mark.parametrize(("target_rate", "kospi_rate", "excess", "relation"), [
    (-0.30, 0.50, -0.80, "opposite"),  # 기준 안인데 코스피는 오르고 종목은 내렸다
    (0.30, -0.50, 0.80, "opposite"),
    (-0.50, 0.50, -1.00, "opposite"),  # 경계: 정확히 −1.00%p 도 기준 안
    (-0.51, 0.50, -1.01, "diverges"),  # 기준을 넘으면 방향과 상관없이 diverges
    (-0.60, 0.50, -1.10, "diverges"),
    (0.00, 0.50, -0.50, "follows"),  # 보합(0.00)은 방향이 없다
    (0.50, 0.00, 0.50, "follows"),
])
def test_kospi_relation_opposite_direction(
    target_rate: float, kospi_rate: float, excess: float, relation: str,
) -> None:
    k = _kospi_ctx(target_rate, kospi_rate, 5.0).kospi
    assert k.kospi_basis == "kospi"
    assert k.excess_vs_kospi_pp == excess
    assert k.kospi_relation == relation


@pytest.mark.parametrize(("target_rate", "kospi_rate", "ex_self"), [(0.80, 0.08, -0.10), (-0.80, -0.08, 0.10)])
def test_kospi_opposite_is_judged_against_ex_self(target_rate: float, kospi_rate: float, ex_self: float) -> None:
    """비중 20%. 코스피와는 방향이 같지만 자기 제외 코스피와는 반대다 → 자기 제외 기준으로 opposite.

    자기 제외 = (코스피 − 0.2 × 종목) / 0.8. 코스피는 종목과 자기 제외 코스피의 가중평균이라,
    반대로 코스피와만 방향이 다르고 자기 제외와는 같은 경우는 생기지 않는다.
    """
    k = _kospi_ctx(target_rate, kospi_rate, 20.0).kospi
    assert k.kospi_basis == "kospi_ex_self"
    assert k.kospi_ex_self_change_rate_pct == ex_self
    assert target_rate * kospi_rate > 0  # 코스피와는 같은 방향
    assert abs(k.excess_vs_kospi_ex_self_pp) <= KOSPI_FOLLOW_THRESHOLD_PP
    assert k.kospi_relation == "opposite"


def test_kospi_relation_judges_the_rounded_excess() -> None:
    """2.14 − 1.14 는 float 로 1.0000000000000002 다. 보이는 숫자(1.00)대로 follows 여야 한다."""
    assert 2.14 - 1.14 > 1.0
    k = _kospi_ctx(2.14, 1.14, 1.0).kospi
    assert k.kospi_basis == "kospi"
    assert k.excess_vs_kospi_pp == 1.00
    assert k.kospi_relation == "follows"


def test_ex_self_excess_is_shown_rate_minus_shown_ex_self() -> None:
    """자기 제외 코스피 −1.635 는 −1.64 로 보인다. 초과분은 보이는 숫자끼리 뺀 7.99 − (−1.64) = 9.63 이어야 한다
    (반올림 전 값과 빼면 9.62)."""
    target = stock("000010", round(1_200_000 * 1.0799), 7.99)  # 전일 시총 비중 12%
    rest = stock("000020", 8_800_000, 0.0)
    k = build_market_context("000010", DAY, kospi(-0.48), [target, rest], groups={}, stock_groups={}).kospi
    assert k.kospi_basis == "kospi_ex_self"
    assert k.kospi_ex_self_change_rate_pct == -1.64
    assert k.excess_vs_kospi_ex_self_pp == 9.63


def test_preferred_stock_is_judged_against_kospi() -> None:
    """우선주는 비중이 없어(분모 밖) 코스피 그대로 비교한다. 시총이 아무리 커도 마찬가지다."""
    k = _kospi_ctx(3.00, 1.00, 50.0, code="000015").kospi
    assert k.kospi_weight_pct is None
    assert k.kospi_basis == "kospi"
    assert k.excess_vs_kospi_pp == 2.00
    assert k.kospi_relation == "diverges"


@pytest.mark.parametrize(("weight_pct", "basis"), [(20.0, "kospi_ex_self"), (5.0, "kospi")])
def test_kospi_relation_none_when_target_has_no_trades(weight_pct: float, basis: str) -> None:
    """거래정지면 어느 기준이든 초과분이 없어 판정하지 않는다. 기준은 비중대로 남긴다."""
    k = _kospi_ctx(0.0, 3.00, weight_pct, target_volume=0).kospi
    assert k.kospi_basis == basis
    assert k.excess_vs_kospi_pp is None and k.excess_vs_kospi_ex_self_pp is None
    assert k.kospi_relation is None


# --- 동종 그룹 ---------------------------------------------------------------------------------


def test_self_is_left_out_of_group_median() -> None:
    """KB금융: 나머지 3사 0.35·0.80·−1.37 의 중앙값 0.35% → 초과분 0.27 − 0.35 = −0.08%p."""
    ctx = build_market_context("105560", DAY, KOSPI, STOCKS)

    [peer] = ctx.peers
    assert peer.group == "은행지주"
    assert peer.members_used == ["055550", "086790", "316140"]
    assert [(e.code, e.reason) for e in peer.members_excluded] == [("105560", "self")]
    assert peer.median_change_rate_pct == 0.35
    assert peer.excess_vs_group_pp == -0.08
    assert peer.peer_count == 3
    assert peer.relation == "follows"


def test_two_member_group_compares_with_the_other() -> None:
    ctx = build_market_context("005930", DAY, KOSPI, STOCKS)

    [peer] = ctx.peers
    assert peer.group == "메모리반도체"
    assert peer.members_used == ["000660"]
    assert peer.median_change_rate_pct == 5.18
    assert peer.excess_vs_group_pp == -0.95  # 4.23 − 5.18
    assert peer.peer_count == 1
    assert peer.relation == "follows"


def test_no_trades_member_is_left_out_of_group_median() -> None:
    """DH오토넥스(2026-10-27 거래량 0, 등락률 0.00)가 들어가면 그룹 등락률이 내려간다."""
    groups = {"시험": {"005930": "삼성전자", "000300": "DH오토넥스", "000660": "SK하이닉스"}}
    ctx = build_market_context("005930", DAY, KOSPI, STOCKS, groups=groups,
                               stock_groups={"005930": ("시험",)})

    [peer] = ctx.peers
    assert peer.members_used == ["000660"]
    assert [(e.code, e.reason) for e in peer.members_excluded] == [
        ("005930", "self"), ("000300", "no_trades")]
    assert peer.median_change_rate_pct == 5.18  # 0.00 을 넣었다면 2.59


def test_missing_member_is_marked_and_skipped() -> None:
    """삼성생명의 보험 그룹: 삼성화재·메리츠는 fixture(=응답)에 없다. 쓸 종목이 없으면 중앙값도 없다."""
    ctx = build_market_context("032830", DAY, KOSPI, STOCKS)

    insurance, samsung_linked = ctx.peers
    assert insurance.group == "보험"
    assert insurance.members_used == []
    assert [(e.code, e.reason) for e in insurance.members_excluded] == [
        ("032830", "self"), ("000810", "missing"), ("138040", "missing")]
    assert insurance.median_change_rate_pct is None and insurance.excess_vs_group_pp is None
    assert insurance.peer_count == 0 and insurance.relation is None

    assert samsung_linked.group == "삼성전자 연동"
    assert samsung_linked.members_used == ["005930", "028260"]
    # 두 종목이면 중앙값 = 두 값의 평균
    assert samsung_linked.median_change_rate_pct == pytest.approx((4.23 + 3.08) / 2, abs=0.005)
    assert samsung_linked.excess_vs_group_pp == pytest.approx(3.45 - (4.23 + 3.08) / 2, abs=0.005)


def _group_ctx(target_rate: float, peer_rates: list[float], *, target_volume: int = 1000):
    """대상 000010 과 비교 종목 000020·000030… 로 된 그룹 하나."""
    peers = [stock(f"0000{i}0", 100, r) for i, r in enumerate(peer_rates, start=2)]
    target = stock("000010", 100, target_rate, volume=target_volume)
    groups = {"시험": {s.code: s.code for s in [target, *peers]}}
    ctx = build_market_context("000010", DAY, kospi(0.0), [target, *peers], groups=groups,
                               stock_groups={"000010": ("시험",)})
    [peer] = ctx.peers
    return peer


@pytest.mark.parametrize(("target_rate", "peer_rates", "excess", "relation"), [
    (2.00, [0.50, 1.50], 1.00, "follows"),  # 경계: 정확히 +1.00%p 는 따라간 것
    (0.00, [0.50, 1.50], -1.00, "follows"),  # 경계: 정확히 −1.00%p
    (2.01, [0.50, 1.50], 1.01, "diverges"),
    (-0.01, [0.50, 1.50], -1.01, "diverges"),
    (2.00, [1.00], 1.00, "follows"),  # 비교 종목이 하나여도 기준 안이면 따라간 것
    (2.01, [1.00], 1.01, "inconclusive"),  # 하나뿐이면 크게 달라도 단정하지 않는다
    (-3.00, [1.00], -4.00, "inconclusive"),
])
def test_group_relation(
    target_rate: float, peer_rates: list[float], excess: float, relation: str,
) -> None:
    peer = _group_ctx(target_rate, peer_rates)
    assert peer.excess_vs_group_pp == excess
    assert peer.peer_count == len(peer_rates) == len(peer.members_used)
    assert peer.relation == relation


def test_group_relation_judges_the_rounded_excess() -> None:
    """2.14 − 1.14 는 float 로 1.0000000000000002 다. 보이는 숫자(1.00)대로 follows 여야 한다."""
    assert 2.14 - 1.14 > 1.0
    peer = _group_ctx(2.14, [1.14])
    assert peer.excess_vs_group_pp == 1.00
    assert peer.relation == "follows"


def test_group_excess_is_shown_rate_minus_shown_median() -> None:
    """−1.88·−1.83 의 중앙값 −1.855 는 −1.85 로 보인다. 독자가 보는 차이는 −2.86 − (−1.85) = −1.01%p 라 diverges 다.
    반올림 전 중앙값과 빼면 −1.005 → −1.00 으로 follows 가 되어 보이는 숫자와 판정이 어긋난다."""
    peer = _group_ctx(-2.86, [-1.88, -1.83])
    assert peer.median_change_rate_pct == -1.85
    assert peer.excess_vs_group_pp == -1.01
    assert peer.relation == "diverges"


@pytest.mark.parametrize(("target_rate", "peer_rates", "center", "excess", "relation"), [
    # 평균(3.43)이면 초과분 −2.43%p 로 diverges. 튀는 9.00 하나에 끌려가지 않는다
    (1.00, [0.50, 0.80, 9.00], 0.80, 0.20, "follows"),
    # 평균(3.17)이면 초과분 −0.17%p 로 follows. 튀는 값이 차이를 가리지 않는다
    (3.00, [0.00, 0.50, 9.00], 0.50, 2.50, "diverges"),
    # 짝수 개면 가운데 두 값(0.80·1.20)의 평균
    (1.50, [0.50, 0.80, 1.20, 9.00], 1.00, 0.50, "follows"),
])
def test_group_uses_median_against_outlier(
    target_rate: float, peer_rates: list[float], center: float, excess: float, relation: str,
) -> None:
    peer = _group_ctx(target_rate, peer_rates)
    assert peer.median_change_rate_pct == center
    assert peer.excess_vs_group_pp == excess
    assert peer.relation == relation


@pytest.mark.parametrize(("target_rate", "peer_rates", "excess", "relation"), [
    (-0.30, [0.40, 0.50], -0.75, "opposite"),  # 기준 안인데 그룹은 오르고 종목은 내렸다
    (-0.30, [0.45], -0.75, "opposite"),  # 비교 종목이 하나여도 기준 안이면 같은 규칙
    (0.40, [-0.50, -0.30, 9.00], 0.70, "opposite"),  # 중앙값(−0.30)의 방향으로 본다
    (-0.60, [0.40, 0.50], -1.05, "diverges"),  # 기준을 넘으면 방향과 상관없이 지금처럼
    (-0.60, [0.45], -1.05, "inconclusive"),
    (0.00, [0.40, 0.50], -0.45, "follows"),  # 보합(0.00)은 방향이 없다
    # 그룹 중앙값이 보합. 비교 종목이 오른 것 하나·내린 것 하나·보합 하나로 반반 엇갈려 follows 가 아니다(group_relation)
    (0.50, [-0.50, 0.00, 0.50], 0.50, "inconclusive"),
])
def test_group_relation_opposite_direction(
    target_rate: float, peer_rates: list[float], excess: float, relation: str,
) -> None:
    peer = _group_ctx(target_rate, peer_rates)
    assert peer.excess_vs_group_pp == excess
    assert peer.relation == relation


@pytest.mark.parametrize(("target_rate", "peer_rates", "excess", "relation"), [
    # 비교 종목 둘: 방향이 엇갈리면 기준 안이어도 inconclusive (2026-11-04 현대모비스: 현대차 +2.16, 기아 −0.83)
    (1.28, [2.16, -0.83], 0.61, "inconclusive"),
    (-1.21, [0.55, -2.78], -0.10, "inconclusive"),
    # 0.00(보합)은 방향이 없어 엇갈림으로 치지 않는다
    (0.50, [0.00, 0.80], 0.10, "follows"),
    (-0.20, [0.00, -0.60], 0.10, "follows"),
    # 셋 이상: 한 방향이 과반이고 대상도 그 방향이면 follows 유지
    (0.27, [0.35, 0.80, -1.37], -0.08, "follows"),  # 2026-10-27 KB금융(오른 둘·내린 하나, KB 상승)
    (-1.39, [-1.86, 1.04, -1.56], 0.17, "follows"),  # 2026-11-04 HD현대중공업(내린 둘·오른 하나, 대상 하락)
    # 셋 이상: 과반 방향이고 대상이 보합(0.00)이면 반대 방향으로 치지 않아 follows 유지
    (0.00, [-0.83, 1.24, 0.67], -0.67, "follows"),  # 2026-10-30 우리금융지주
    # 셋 이상: 오른 수 = 내린 수(반반)면 inconclusive. 보합은 어느 쪽에도 세지 않는다
    (0.67, [-0.83, 1.24, 0.00], 0.67, "inconclusive"),  # 2026-10-30 하나금융지주
    (0.30, [0.40, -0.20, 0.50, -0.10], 0.15, "inconclusive"),
    # 넷 이상에서 과반이 없으면(오른 둘·내린 하나·보합 하나) inconclusive
    (0.30, [0.50, 0.20, -0.40, 0.00], 0.20, "inconclusive"),
    # 기준 초과·반대 방향은 엇갈림과 상관없이 그대로
    (3.00, [-0.50, 1.00], 2.75, "diverges"),
    (-0.30, [0.90, -0.10], -0.70, "opposite"),
    (2.01, [1.00], 1.01, "inconclusive"),  # 비교 종목 하나: 지금처럼
])
def test_group_relation_mixed_direction(
    target_rate: float, peer_rates: list[float], excess: float, relation: str,
) -> None:
    peer = _group_ctx(target_rate, peer_rates)
    assert peer.excess_vs_group_pp == excess
    assert peer.relation == relation


def test_is_mixed_ignores_flat() -> None:
    assert is_mixed([2.16, -0.83])
    assert not is_mixed([0.00, 0.80]) and not is_mixed([0.00, -0.80]) and not is_mixed([0.00, 0.00])
    assert not is_mixed([]) and not is_mixed([1.0])


@pytest.mark.parametrize(("stock_rate", "member_rates", "kept"), [
    (1.28, [2.16, -0.83], False),  # 비교 종목 둘이면 유지하지 않는다
    (0.27, [0.35, 0.80, -1.37], True),
    (0.00, [-0.83, 1.24, 0.67], True),  # 대상 보합
    (-0.10, [0.35, 0.80, -1.37], False),  # 대상이 과반 반대 방향(실제로는 opposite 가 먼저 걸린다)
    (0.67, [-0.83, 1.24, 0.00], False),  # 반반
    (None, [0.35, 0.80, -1.37], False),
])
def test_mixed_still_follows(stock_rate: float | None, member_rates: list[float], kept: bool) -> None:
    assert mixed_still_follows(stock_rate, member_rates) is kept


def test_group_relation_without_member_rates_is_unchanged() -> None:
    """비교 종목 등락률을 넘기지 않는 호출은 지금과 같다(엇갈림을 보지 않는다)."""
    assert group_relation(0.61, 2, 1.28, 0.67) == "follows"
    assert group_relation(0.61, 2, 1.28, 0.67, [2.16, -0.83]) == "inconclusive"


def test_group_relation_none_without_median() -> None:
    """비교 종목이 전부 응답에 없으면 중앙값이 없고 판정도 없다."""
    target = stock("000010", 100, 2.0)
    other = stock("000090", 100, 0.0)  # 그룹 밖 종목. 시장이 대상 하나뿐이면 비중이 100% 가 된다
    groups = {"시험": {"000010": "대상", "000020": "없음1", "000030": "없음2"}}
    ctx = build_market_context("000010", DAY, kospi(0.0), [target, other], groups=groups,
                               stock_groups={"000010": ("시험",)})

    [peer] = ctx.peers
    assert peer.median_change_rate_pct is None
    assert peer.peer_count == 0
    assert peer.relation is None


def test_group_relation_none_when_target_has_no_trades() -> None:
    """중앙값은 있어도 대상이 거래정지면 초과분이 없어 판정하지 않는다."""
    peer = _group_ctx(0.0, [0.50, 1.50], target_volume=0)
    assert peer.median_change_rate_pct == 1.00
    assert peer.peer_count == 2
    assert peer.excess_vs_group_pp is None
    assert peer.relation is None


def test_stock_without_group_has_empty_peers() -> None:
    ctx = build_market_context("095570", DAY, KOSPI, STOCKS)  # AJ네트웍스: 그룹 정의 밖
    assert ctx.status == "ok"
    assert ctx.peers == []


# --- 거래정지·데이터 없음 ----------------------------------------------------------------------


def test_no_trades_target_has_no_excess_or_contribution() -> None:
    groups = {"시험": {"000300": "DH오토넥스", "005930": "삼성전자", "000660": "SK하이닉스"}}
    ctx = build_market_context("000300", DAY, KOSPI, STOCKS, groups=groups,
                               stock_groups={"000300": ("시험",)})

    assert ctx.status == "no_trades"
    assert "거래정지" in ctx.status_reason
    k = ctx.kospi
    assert k.stock_change_rate_pct == 0.0 and k.kospi_change_rate_pct == 3.09
    assert k.excess_vs_kospi_pp is None
    assert k.kospi_contribution_pp is None
    assert k.kospi_ex_self_change_rate_pct is None and k.excess_vs_kospi_ex_self_pp is None
    assert k.kospi_weight_pct is not None  # 비중은 거래와 관계없이 있다
    assert k.kospi_relation is None
    [peer] = ctx.peers
    assert peer.median_change_rate_pct is not None  # 그룹 중앙값은 낸다
    assert peer.excess_vs_group_pp is None


@pytest.mark.parametrize(("kospi_row", "stocks"), [(None, []), (KOSPI, [])])
def test_no_data_day(kospi_row: IndexDaily | None, stocks: list[StockDaily]) -> None:
    ctx = build_market_context("005930", DAY, kospi_row, stocks)
    assert ctx.status == "no_data"
    assert "데이터가 없다" in ctx.status_reason
    assert ctx.kospi is None and ctx.peers == []


def test_stock_not_in_response() -> None:
    ctx = build_market_context("999990", DAY, KOSPI, STOCKS)
    assert ctx.status == "stock_not_found"
    assert ctx.kospi is None and ctx.peers == []


def test_result_serializes_with_units_in_names() -> None:
    dumped = build_market_context("105560", DAY, KOSPI, STOCKS).model_dump(mode="json")
    assert dumped["bas_dd"] == "2026-10-27"
    assert {"excess_vs_kospi_pp", "kospi_weight_pct", "kospi_contribution_pp",
            "common_prev_market_cap_krw"} <= set(dumped["kospi"])
    assert dumped["peers"][0]["members_excluded"] == [
        {"code": "105560", "name": "KB금융", "reason": "self"}]


# --- 그룹 정의 ---------------------------------------------------------------------------------


def test_every_target_group_exists_and_contains_the_target() -> None:
    for code, names in STOCK_GROUPS.items():
        for name in names:
            assert name in GROUPS, f"{code} 의 그룹 {name!r} 이 GROUPS 에 없다"
            assert code in GROUPS[name], f"{code} 가 자기 그룹 {name!r} 구성원에 없다"


def test_group_definitions_as_specified() -> None:
    assert len(GROUPS) == 16
    assert len(STOCK_GROUPS) == 30
    assert groups_of("032830") == ("보험", "삼성전자 연동")  # 삼성생명은 두 그룹
    assert groups_of("066570") == () and groups_of("033780") == ()  # LG전자·KT&G
    assert groups_of("999990") == ()
    for members in GROUPS.values():
        assert all(len(code) == 6 for code in members)
