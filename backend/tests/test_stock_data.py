import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.services.market_data import MarketDataError
from app.services.stock_data import DailyPrice, fetch_catalog, fetch_prices, fetch_snapshot


class FakeKis:
    def __init__(self, body):
        self.body = body
        self.calls = []

    async def get(self, path, tr_id, params):
        self.calls.append((path, tr_id, params))
        return self.body


@pytest.mark.asyncio
async def test_snapshot_normalizes_quote_and_kis_market_cap_units():
    kis = FakeKis({
        "output": {
            "stck_prpr": "62,400", "prdy_vrss": "-680", "prdy_ctrt": "-1.08",
            "acml_vol": "123", "acml_tr_pbmn": "7654321", "hts_avls": "3720000",
            "per": "12.2", "pbr": "1.3", "eps": "5100", "bps": "48000",
            "hts_frgn_ehrt": "51.2", "w52_hgpr": "70000", "w52_lwpr": "55000",
        }
    })
    result = await fetch_snapshot(kis, "005930")
    assert result.quote["price"] == Decimal(62400)
    assert result.quote["change_amount"] == Decimal(-680)
    assert result.quote["market_cap"] == Decimal(372000000000000)
    assert result.quote["source_as_of"] is None
    assert result.metrics["foreign_ownership"] == Decimal("51.2")


@pytest.mark.asyncio
async def test_snapshot_keeps_quote_when_metric_is_malformed_and_treats_zero_optional_as_missing():
    kis = FakeKis({"output": {
        "stck_prpr": "100", "prdy_vrss": "1", "prdy_ctrt": "1", "acml_vol": "2",
        "acml_tr_pbmn": "3", "hts_avls": "0", "per": "bad", "w52_hgpr": "0",
    }})
    result = await fetch_snapshot(kis, "000660")
    assert result.quote is not None and result.quote["price"] == Decimal(100)
    assert result.quote_error is None
    assert result.metrics is None
    assert result.metrics_error == "INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_snapshot_rejects_market_cap_that_exceeds_safe_integer():
    kis = FakeKis({"output": {
        "stck_prpr": "100", "prdy_vrss": "1", "prdy_ctrt": "1", "acml_vol": "2",
        "acml_tr_pbmn": "3", "hts_avls": "100000000",
    }})
    result = await fetch_snapshot(kis, "000660")
    assert result.quote is None
    assert result.quote_error == "INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_prices_uses_raw_adjustment_and_rejects_bad_ohlc():
    kis = FakeKis({"output2": [{
        "stck_bsop_date": "20260918", "stck_oprc": "10", "stck_hgpr": "12",
        "stck_lwpr": "9", "stck_clpr": "11", "acml_vol": "4",
    }]})
    result = await fetch_prices(kis, "005930", date(2026, 9, 1), date(2026, 9, 30))
    assert result == [DailyPrice(date(2026, 9, 18), Decimal(10), Decimal(12), Decimal(9), Decimal(11), 4)]
    assert kis.calls[0][1] == "FHKST03010100"
    assert kis.calls[0][2]["FID_ORG_ADJ_PRC"] == "1"

    bad = FakeKis({"output2": [{
        "stck_bsop_date": "20260918", "stck_oprc": "10", "stck_hgpr": "8",
        "stck_lwpr": "9", "stck_clpr": "11", "acml_vol": "4",
    }]})
    with pytest.raises(MarketDataError):
        await fetch_prices(bad, "005930", date(2026, 9, 1), date(2026, 9, 30))

    halted = FakeKis({"output2": [{
        "stck_bsop_date": "20260918", "stck_oprc": "0", "stck_hgpr": "0",
        "stck_lwpr": "0", "stck_clpr": "0", "acml_vol": "0",
    }]})
    assert (await fetch_prices(halted, "005930", date(2026, 9, 1), date(2026, 9, 30)))[0].close == Decimal(0)

    duplicate = FakeKis({"output2": [
        {"stck_bsop_date": "20260918", "stck_oprc": "1", "stck_hgpr": "1", "stck_lwpr": "1", "stck_clpr": "1", "acml_vol": "1"},
        {"stck_bsop_date": "20260918", "stck_oprc": "1", "stck_hgpr": "1", "stck_lwpr": "1", "stck_clpr": "1", "acml_vol": "1"},
    ]})
    with pytest.raises(MarketDataError):
        await fetch_prices(duplicate, "005930", date(2026, 9, 1), date(2026, 9, 30))


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeHttp:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def get(self, url):
        return next(self.responses)


def _master(code, name, market, extra_code=None):
    tail_length, listed_offset = ((227, 105) if market == "KOSPI" else (221, 100))
    tail = bytearray(b" " * tail_length)
    tail[listed_offset : listed_offset + 8] = b"19750113"
    line = f"{code:<9}{'X'*12}{name}".encode("cp949") + bytes(tail) + b"\n"
    if extra_code:
        line += f"{extra_code:<9}{'X'*12}{'펀드':<20}".encode("cp949") + bytes(tail) + b"\n"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("master.mst", line)
    return out.getvalue()


@pytest.mark.asyncio
async def test_catalog_is_combined_atomically():
    client = FakeHttp([
        FakeResponse(_master("005930", "삼성전자", "KOSPI", "F70100030")),
        FakeResponse(_master("035720", "카카오", "KOSDAQ", "A12345678")),
    ])
    result = await fetch_catalog(client)
    assert [(item.code, item.market, item.name) for item in result] == [
        ("005930", "KOSPI", "삼성전자"), ("035720", "KOSDAQ", "카카오")
    ]
    assert result[0].listed_at == date(1975, 1, 13)
