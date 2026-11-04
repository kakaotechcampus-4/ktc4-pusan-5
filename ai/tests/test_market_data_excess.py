"""코스피 대비 초과 등락."""

from datetime import date

import pytest

from app.services.market_data import IndexDaily, StockDaily, compute_excess, excess_return

DAY = date(2026, 9, 10)


def stock(change_rate: float | None, *, bas_dd: date = DAY, volume: int | None = 1000) -> StockDaily:
    return StockDaily(
        bas_dd=bas_dd, code="005930", name="삼성전자", market="KOSPI", close=62400, change=-680,
        change_rate=change_rate, open=None, high=None, low=None, volume=volume, trade_value=None,
        market_cap=None, listed_shares=None,
    )


def kospi(change_rate: float | None, *, bas_dd: date = DAY) -> IndexDaily:
    return IndexDaily(
        bas_dd=bas_dd, series="KOSPI", name="코스피", close=7033.92, change=-17.72,
        change_rate=change_rate, open=None, high=None, low=None, volume=None, trade_value=None,
        market_cap=None,
    )


@pytest.mark.parametrize(
    ("stock_rate", "index_rate", "expected"),
    [
        (0.24, -0.25, 0.49),  # 부동소수점 그대로면 0.49000000000000005
        (-1.08, -0.25, -0.83),  # 시장보다 더 내렸다
        (-1.0, -2.0, 1.0),  # 내렸지만 시장보다 덜 내렸다
        (1.5, 1.5, 0.0),  # 시장만큼 움직였다
    ],
)
def test_excess_return(stock_rate: float, index_rate: float, expected: float) -> None:
    assert excess_return(stock_rate, index_rate) == expected


def test_compute_excess() -> None:
    move = compute_excess(stock(-1.08), kospi(-0.25))

    assert move.bas_dd == DAY
    assert move.code == "005930"
    assert move.stock_change_rate == -1.08
    assert move.index_change_rate == -0.25
    assert move.excess_rate == -0.83


def test_different_days_are_not_compared() -> None:
    with pytest.raises(ValueError, match="기준일"):
        compute_excess(stock(-1.08), kospi(-0.25, bas_dd=date(2026, 9, 9)))


def test_missing_rate_is_not_treated_as_zero() -> None:
    with pytest.raises(ValueError, match="005930"):
        compute_excess(stock(None), kospi(-0.25))
    with pytest.raises(ValueError, match="코스피"):
        compute_excess(stock(-1.08), kospi(None))


def test_no_trade_stock_has_no_excess() -> None:
    # 거래정지면 등락률이 0.00 으로 온다. 계산하면 코스피를 뒤집은 −(−0.25) = +0.25%p 가 된다
    assert compute_excess(stock(0.0, volume=0), kospi(-0.25)) is None


def test_unknown_volume_is_not_no_trade() -> None:
    # 거래량을 모르는 것(None)과 0 은 다르다. 0 일 때만 거른다
    assert compute_excess(stock(-1.08, volume=None), kospi(-0.25)).excess_rate == -0.83
