from datetime import date
from decimal import Decimal

import pytest

from app.services.market_data import MarketDataError
from app.services.stock_financials import AnnualEps, AnnualIncome, fetch_eps, fetch_income


class FakeKis:
    def __init__(self, body):
        self.body, self.calls = body, []

    async def get(self, path, tr_id, params):
        self.calls.append((path, tr_id, params))
        return self.body


@pytest.mark.asyncio
async def test_income_annual_dict_output_preserves_fiscal_month():
    kis = FakeKis(
        {
            "output": {
                "stac_yymm": "202503",
                "sale_account": "100",
                "bsop_prti": "20",
                "thtr_ntin": "10",
            }
        }
    )
    assert await fetch_income(kis, "000660") == [
        AnnualIncome(
            date(2025, 3, 31), Decimal(10000000000), Decimal(2000000000), Decimal(1000000000)
        )
    ]
    assert kis.calls[0][1] == "FHKST66430200"


@pytest.mark.asyncio
async def test_eps_list_is_sorted_and_blank_is_none():
    kis = FakeKis(
        {"output": [{"stac_yymm": "202412", "eps": ""}, {"stac_yymm": "202503", "eps": "2.5"}]}
    )
    assert await fetch_eps(kis, "000660") == [
        AnnualEps(date(2024, 12, 31), None),
        AnnualEps(date(2025, 3, 31), Decimal("2.5")),
    ]
    assert kis.calls[0][2] == {
        "FID_DIV_CLS_CODE": "0",
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": "000660",
    }


@pytest.mark.asyncio
async def test_zero_and_negative_values_are_preserved_and_nan_rejected():
    kis = FakeKis(
        {
            "output": {
                "stac_yymm": "202412",
                "sale_account": "0",
                "bsop_prti": "-2",
                "thtr_ntin": "0",
            }
        }
    )
    assert (await fetch_income(kis, "000660"))[0].revenue == Decimal(0)
    assert (await fetch_income(kis, "000660"))[0].operating_profit == Decimal(-200000000)
    bad = FakeKis({"output": {"stac_yymm": "202412", "eps": "NaN"}})
    with pytest.raises(MarketDataError):
        await fetch_eps(bad, "000660")
    too_large = FakeKis({"output": {"stac_yymm": "202412", "sale_account": "100000000"}})
    with pytest.raises(MarketDataError):
        await fetch_income(too_large, "000660")


@pytest.mark.asyncio
async def test_rejects_duplicate_or_bad_period():
    kis = FakeKis(
        {
            "output": [
                {"stac_yymm": "202412", "sale_account": "1"},
                {"stac_yymm": "202412", "sale_account": "2"},
            ]
        }
    )
    with pytest.raises(MarketDataError):
        await fetch_income(kis, "000660")


@pytest.mark.parametrize(
    "row",
    [
        {"stac_yymm": "202413", "eps": "0"},
        {"stac_yymm": "000012", "eps": "0"},
        {"stac_yymm": "202412", "renamed_eps": "1"},
    ],
)
async def test_invalid_period_or_changed_payload_is_failure(row):
    with pytest.raises(MarketDataError):
        await fetch_eps(FakeKis({"output": [row]}), "000660")
