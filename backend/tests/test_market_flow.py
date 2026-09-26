from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.core.config import settings
from app.schemas.market_flow import FLOW_KINDS
from app.services.kis import KisClient
from app.services.krx import fetch_market, parse_sectors
from app.services.market_data import INDICATORS, MarketDataError
from app.services.market_flow import market_flow_boards, parse_flow


def raw(code, qty):
    return {
        "mksc_shrn_iscd": code,
        "hts_kor_isnm": "테스트",
        "ntby_qty": str(qty),
        "frgn_ntby_qty": "1",
        "orgn_ntby_qty": "2",
        "etc_corp_ntby_vol": "3",
    }


def test_flow_uses_upstream_total_including_other_corporations():
    assert parse_flow([raw("005930", 6)], "flowBuy")[0].net_volume == 6
    assert parse_flow([raw("005930", -6)], "flowSell")[0].net_volume == -6
    assert parse_flow([raw("005930", 0)], "flowBuy") == []
    assert parse_flow([], "flowSell") == []


@pytest.mark.parametrize(
    "rows",
    [
        [raw("005930", 1), raw("000660", 2)],
        [raw("005930", 2), raw("005930", 1)],
        [raw("005930", "NaN")],
    ],
)
def test_invalid_flow_does_not_replace_snapshot(rows):
    with pytest.raises((MarketDataError, ValueError)):
        parse_flow(rows, "flowBuy")


def row(name, change, day="20260918"):
    return {"IDX_NM": name, "FLUC_RT": change, "BAS_DD": day, "CLSPRC_IDX": "100"}


def test_sector_allowlist_excludes_composite_size_and_theme_indices():
    items = parse_sectors(
        [
            row("코스피", "10"),
            row("코스피 대형주", "12"),
            row("코스피 200 정보기술", "15"),
            row("제조", "13"),
            row("건설", "-1"),
            row("전기전자", "4.46"),
            row("화학", "0"),
        ]
    )
    assert [(item.name, item.change) for item in items] == [
        ("전기전자", 4.46),
        ("화학", 0),
        ("건설", -1),
    ]
    assert items[0].as_of.isoformat() == "2026-09-18"


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row("건설", "")],
        [row("건설", "1"), row("건설", "2")],
        [row("건설", "1"), row("화학", "2", "20260917")],
    ],
)
def test_bad_sector_batch_is_rejected(rows):
    with pytest.raises((MarketDataError, ValueError)):
        parse_sectors(rows)


@respx.mock
async def test_quote_and_sectors_share_one_krx_request(monkeypatch):
    monkeypatch.setattr(settings, "krx_auth_key", "test-only")
    route = respx.get(settings.krx_api_base_url + "/idx/kospi_dd_trd").respond(
        200, json={"OutBlock_1": [row("코스피", "2.66"), row("전기전자", "4.46")]}
    )
    async with httpx.AsyncClient() as client:
        result = await fetch_market(client, next(i for i in INDICATORS if i.code == "kospi"))
    assert route.call_count == 1
    assert float(result.quote.change) == 2.66
    assert result.sectors[0].change == 4.46


@respx.mock
async def test_flow_request_parameters_and_signed_order(monkeypatch):
    monkeypatch.setattr(settings, "kis_app_key", "test-only")
    monkeypatch.setattr(settings, "kis_app_secret", "test-only")
    auth = respx.post(settings.kis_api_base_url + "/oauth2/tokenP").respond(
        200, json={"access_token": "test-token", "expires_in": 86400}
    )

    def response(request):
        p = request.url.params
        assert p["FID_ETC_CLS_CODE"] == "0"
        assert p["FID_DIV_CLS_CODE"] == "0"
        assert p["FID_INPUT_ISCD"] == "0000"
        assert request.headers["tr_id"] == "FHPTJ04400000"
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "output": [raw("005930", 6 if p["FID_RANK_SORT_CLS_CODE"] == "0" else -6)],
            },
        )

    respx.get(
        settings.kis_api_base_url + "/uapi/domestic-stock/v1/quotations/foreign-institution-total"
    ).mock(side_effect=response)
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        items = [await kis.fetch_flow(kind) for kind in FLOW_KINDS]
    assert auth.call_count == 1
    assert [item[0].net_volume for item in items] == [6, -6]


def test_boards_have_independent_statuses_and_refresh_intervals():
    now = datetime.now(UTC)
    flows, sectors = market_flow_boards(
        {
            "flowBuy": SimpleNamespace(
                items=[
                    i.model_dump(mode="json")
                    for i in parse_flow([raw(f"{i:06}", 100 - i) for i in range(10)], "flowBuy")
                ],
                collected_at=now - timedelta(seconds=181),
                error_code=None,
            ),
            "flowSell": SimpleNamespace(items=None, collected_at=None, error_code="NO_DATA"),
            "sectorKospi": SimpleNamespace(
                items=[i.model_dump(mode="json") for i in parse_sectors([row("건설", "1")])],
                collected_at=now - timedelta(seconds=181),
                error_code=None,
            ),
        }
    )
    assert [b.status for b in flows] == ["stale", "unavailable"]
    assert len(flows[0].items) == 5
    assert [b.status for b in sectors] == ["ready", "pending"]


@pytest.mark.parametrize("bad_part", ["quote", "sectors"])
@respx.mock
async def test_krx_partial_failure_preserves_the_other_result(monkeypatch, bad_part):
    monkeypatch.setattr(settings, "krx_auth_key", "test-only")
    rows = [row("코스피", "2.66"), row("건설", "1")]
    rows[0 if bad_part == "quote" else 1]["FLUC_RT"] = ""
    respx.get(settings.krx_api_base_url + "/idx/kospi_dd_trd").respond(
        200, json={"OutBlock_1": rows}
    )
    async with httpx.AsyncClient() as client:
        result = await fetch_market(client, INDICATORS[0])
    if bad_part == "quote":
        assert result.quote is None
        assert result.quote_error == "INVALID_QUOTE"
        assert result.sectors[0].change == 1
        assert result.sectors_error is None
    else:
        assert float(result.quote.change) == 2.66
        assert result.quote_error is None
        assert result.sectors is None
        assert result.sectors_error == "INVALID_SECTORS"


async def test_sector_older_response_preserves_values_and_marks_stale():
    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.ranking import RankingSnapshot
    from app.repositories.ranking import save_ranking

    async with SessionLocal() as session:
        try:
            await session.execute(
                delete(RankingSnapshot).where(RankingSnapshot.kind == "sectorKospi")
            )
            now = datetime.now(UTC)
            latest = parse_sectors([row("건설", "2", "20260918")])
            await save_ranking(session, "sectorKospi", latest, None, now)
            saved = await session.get(RankingSnapshot, "sectorKospi")
            collected_at = saved.collected_at
            await save_ranking(
                session,
                "sectorKospi",
                parse_sectors([row("건설", "1", "20260917")]),
                None,
                now + timedelta(seconds=3600),
            )
            await session.refresh(saved)
            assert saved.items[0]["as_of"] == "2026-09-18"
            assert saved.items[0]["change"] == 2
            assert saved.collected_at == collected_at
            assert saved.checked_at == now + timedelta(seconds=3600)
            assert saved.error_code == "OUTDATED_RESPONSE"
            assert market_flow_boards({"sectorKospi": saved})[1][0].status == "stale"
            for day in ("20260918", "20260921"):
                await save_ranking(
                    session, "sectorKospi", parse_sectors([row("건설", "3", day)]), None, now
                )
                await session.refresh(saved)
                assert saved.items[0]["change"] == 3
                assert saved.error_code is None
            assert saved.items[0]["as_of"] == "2026-09-21"
        finally:
            await session.rollback()
