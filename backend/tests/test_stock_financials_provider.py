from datetime import date
from decimal import Decimal

import pytest

from app.services.market_data import MarketDataError
from app.services.stock_financials import (
    AnnualEps,
    AnnualIncome,
    AnnualStability,
    fetch_eps,
    fetch_income,
    fetch_quarterly_income,
    fetch_quarterly_ratios,
    fetch_stability,
)


class FakeKis:
    def __init__(self, body):
        self.body, self.calls = body, []

    async def get(self, path, tr_id, params):
        self.calls.append((path, tr_id, params))
        return self.body


class SequenceKis(FakeKis):
    def __init__(self, bodies):
        super().__init__(bodies[0])
        self.bodies = iter(bodies)

    async def get(self, path, tr_id, params):
        self.calls.append((path, tr_id, params))
        body = next(self.bodies)
        if isinstance(body, Exception):
            raise body
        return body


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
        {
            "output": [
                {"stac_yymm": "202412", "eps": "", "roe_val": "92.68", "lblt_rate": "32.80"},
                {"stac_yymm": "202503", "eps": "2.5"},
            ]
        }
    )
    assert await fetch_eps(kis, "000660") == [
        AnnualEps(date(2024, 12, 31), None, Decimal("92.68"), Decimal("32.80")),
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


@pytest.mark.asyncio
async def test_stability_requires_current_ratio_and_preserves_percent():
    kis = FakeKis({"output": {"stac_yymm": "202512", "crnt_rate": "259.15"}})
    assert await fetch_stability(kis, "000660") == [
        AnnualStability(date(2025, 12, 31), Decimal("259.15"))
    ]
    assert kis.calls[0][1] == "FHKST66430600"
    with pytest.raises(MarketDataError):
        await fetch_stability(FakeKis({"output": {"stac_yymm": "202512"}}), "000660")


@pytest.mark.asyncio
async def test_quarterly_uses_selector_one_and_preserves_cumulative_values():
    income = SequenceKis(
        [
            {
                "output": {
                    "stac_yymm": "202506",
                    "sale_account": "0",
                    "bsop_prti": "-2",
                    "thtr_ntin": "3",
                }
            },
            {"output": {"setl_mmdd": "1231"}},
        ]
    )
    row = (await fetch_quarterly_income(income, "000660"))[0]
    assert row.revenue == Decimal(0) and row.operating_profit == Decimal(-200000000)
    assert row.fiscal_year_end_month == 12
    assert income.calls[0][2]["FID_DIV_CLS_CODE"] == "1"
    ratios = FakeKis({"output": {"stac_yymm": "202506", "eps": "4.2"}})
    assert (await fetch_quarterly_ratios(ratios, "000660"))[0].eps == Decimal("4.2")
    assert ratios.calls[0][2]["FID_DIV_CLS_CODE"] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setl_mmdd,expected", [("0331", 3), ("0229", 2), ("12", 12), ("03", 3), ("", None)]
)
async def test_quarterly_fiscal_metadata_validates_mmdd(setl_mmdd, expected):
    kis = SequenceKis(
        [
            {"output": {"stac_yymm": "202506", "sale_account": "1"}},
            {"output": {"setl_mmdd": setl_mmdd}},
        ]
    )
    assert (await fetch_quarterly_income(kis, "000660"))[0].fiscal_year_end_month == expected


@pytest.mark.asyncio
async def test_quarterly_fiscal_metadata_failures_propagate():
    for body in ({"output": {"setl_mmdd": "0230"}}, {"output": {"setl_mmdd": "1231"}}):
        first = {"output": {"stac_yymm": "202506", "sale_account": "1"}}
        if body["output"]["setl_mmdd"] == "1231":
            body = MarketDataError("UPSTREAM_ERROR")
        with pytest.raises((MarketDataError, StopAsyncIteration)):
            await fetch_quarterly_income(SequenceKis([first, body]), "000660")
