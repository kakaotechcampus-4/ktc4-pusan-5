from datetime import date
from decimal import Decimal

import pytest

from app.services.market_data import MarketDataError
from app.services.stock_history import fetch_cap, fetch_rs


class FakeKis:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    async def get(self, path, tr_id, params):
        self.calls.append(params)
        return {"output2": next(self.rows)}


async def test_cap_uses_last_trading_day_and_does_not_backfill_unlisted_stock():
    async def cache(market, kind, day):
        return (
            []
            if day == date(2025, 12, 31)
            else [{"ISU_CD": "005930", "BAS_DD": "20251230", "MKTCAP": "100"}]
        )

    assert await fetch_cap(None, "005930", "KOSPI", date(2025, 12, 31), cache) == {
        "market_cap": Decimal(100),
        "cap_as_of": date(2025, 12, 30),
    }
    assert await fetch_cap(None, "000660", "KOSPI", date(2025, 12, 31), cache) is None


async def test_rs_fetches_two_bounded_adjusted_windows_with_matching_index_dates():
    kis = FakeKis(
        [
            [{"stck_bsop_date": "20251230", "stck_clpr": "120"}],
            [{"stck_bsop_date": "20241230", "stck_clpr": "100"}],
        ]
    )

    async def cache(market, kind, day):
        return [
            {
                "IDX_NM": "코스피",
                "BAS_DD": day.strftime("%Y%m%d"),
                "CLSPRC_IDX": "110" if day.year == 2025 else "100",
            }
        ]

    result = await fetch_rs(kis, "005930", "KOSPI", date(2025, 12, 31), cache)
    assert result["rs"] == Decimal(10)
    assert result["rs_as_of"] == date(2025, 12, 30)
    assert result["rs_base_date"] == date(2024, 12, 30)
    assert len(kis.calls) == 2
    for params in kis.calls:
        assert params["FID_ORG_ADJ_PRC"] == "0"
        assert (
            date.fromisoformat(params["FID_INPUT_DATE_2"])
            - date.fromisoformat(params["FID_INPUT_DATE_1"])
        ).days == 14


@pytest.mark.parametrize(
    "rows",
    [
        [{"stck_bsop_date": "20260102", "stck_clpr": "100"}],
        [{"stck_bsop_date": "20251230", "stck_clpr": "100"}] * 2,
        [{"stck_bsop_date": "20251230", "stck_clpr": "NaN"}],
    ],
)
async def test_bad_rs_source_is_rejected(rows):
    with pytest.raises(MarketDataError):
        await fetch_rs(FakeKis([rows]), "005930", "KOSPI", date(2025, 12, 31), None)


async def test_rs_does_not_replace_zero_latest_close_with_older_positive_close():
    kis = FakeKis(
        [
            [
                {"stck_bsop_date": "20251230", "stck_clpr": "0"},
                {"stck_bsop_date": "20251229", "stck_clpr": "100"},
            ]
        ]
    )
    assert await fetch_rs(kis, "005930", "KOSPI", date(2025, 12, 31), None) is None


async def test_rs_leap_year_base_and_insufficient_history():
    kis = FakeKis([[{"stck_bsop_date": "20240229", "stck_clpr": "100"}], []])
    assert await fetch_rs(kis, "005930", "KOSPI", date(2024, 2, 29), None) is None
    assert kis.calls[1]["FID_INPUT_DATE_2"] == "20230228"
