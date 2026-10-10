"""DART 공시 목록 어댑터와 수집기의 고르기. DB 저장은 tests/test_dart_disclosure_db.py."""

from datetime import date

import httpx
import pytest
import respx

from app.collectors import disclosure as collector
from app.collectors.disclosure import CollectResult, select_items
from app.core.config import settings
from app.core.scope import ScopeError, SourceScope, parse_scope
from app.services.dart import client as dart
from app.services.dart.client import LIST_URL, DartError, parse_list

DAY = date(2026, 10, 8)


def raw(rcept_no="20261008000123", stock_code="005930", **values):
    return {
        "corp_code": "00126380", "corp_name": "삼성전자 ", "stock_code": stock_code,
        "corp_cls": "Y", "report_nm": "주요사항보고서(자기주식취득결정)  ",
        "rcept_no": rcept_no, "flr_nm": "삼성전자", "rcept_dt": "20261008", "rm": "유",
        **values,
    }


def page(rows, total_page=1):
    return {"status": "000", "message": "정상", "total_page": total_page, "list": rows}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(settings, "dart_api_key", "test-key")


def test_parse_list_cleans_fields_and_skips_unlisted_companies():
    [item] = parse_list([raw(rm=""), raw(rcept_no="20261008000999", stock_code=" ")])
    assert item.corp_name == "삼성전자"
    assert item.report_nm == "주요사항보고서(자기주식취득결정)"
    assert item.rcept_dt == DAY
    assert item.rm is None


@respx.mock
async def test_fetch_day_reads_every_page_of_kospi(key):
    route = respx.get(LIST_URL).mock(side_effect=[
        httpx.Response(200, json=page([raw("1")], total_page=2)),
        httpx.Response(200, json=page([raw("2")], total_page=2)),
    ])
    items = await dart.fetch_day(DAY)
    assert [i.rcept_no for i in items] == ["1", "2"]
    params = route.calls.last.request.url.params
    assert params["page_no"] == "2"
    assert params["bgn_de"] == params["end_de"] == "20261008"
    assert params["corp_cls"] == "Y"


@respx.mock
async def test_fetch_day_treats_no_data_as_empty(key):
    respx.get(LIST_URL).mock(return_value=httpx.Response(
        200, json={"status": "013", "message": "조회된 데이타가 없습니다."}))
    assert await dart.fetch_day(DAY) == []


@respx.mock
async def test_fetch_day_raises_on_error_status_without_leaking_key(key):
    respx.get(LIST_URL).mock(return_value=httpx.Response(
        200, json={"status": "020", "message": "요청 제한을 초과하였습니다."}))
    with pytest.raises(DartError, match="020") as error:
        await dart.fetch_day(DAY)
    assert "test-key" not in str(error.value)


async def test_fetch_day_needs_a_key(monkeypatch):
    monkeypatch.setattr(settings, "dart_api_key", "")
    with pytest.raises(RuntimeError, match="DART_API_KEY"):
        await dart.fetch_day(DAY)


def test_select_items_keeps_allowed_new_disclosures_up_to_the_limit():
    source = SourceScope("dart", enabled=True, allowed=frozenset({"005930"}), max_items=3)
    items = parse_list([
        raw("1"), raw("2", stock_code="000660"), raw("3"), raw("3"), raw("4"), raw("5"),
    ])
    result = CollectResult()
    kept = select_items(items, source=source, known={"1"}, collected=1, result=result)
    assert [i.rcept_no for i in kept] == ["3", "4"]  # 1 은 이미 있고, 상한 3 - 1 = 2건
    assert result.matched == 5 and result.held == 1


def scope(enabled=True, **values):
    return parse_scope({
        "period": {"start": date(2026, 10, 6), "end": date(2026, 10, 31)},
        "sources": {"dart": {"enabled": enabled, "stock_codes": ["005930"], "max_items": 10,
                             "terms": {"status": "미확인"}, **values}},
    })


def test_enabled_dart_needs_stock_codes():
    with pytest.raises(ScopeError, match="stock_codes"):
        scope(stock_codes=[])


async def test_disabled_source_is_refused_before_calling_dart(monkeypatch):
    monkeypatch.setattr(collector.dart, "fetch_day", lambda *a, **k: pytest.fail("불렀다"))
    with pytest.raises(ScopeError, match="꺼져 있다"):
        await collector.collect(DAY, scope=scope(enabled=False))


async def test_day_outside_the_period_is_not_requested(monkeypatch):
    monkeypatch.setattr(collector.dart, "fetch_day", lambda *a, **k: pytest.fail("불렀다"))
    result = await collector.collect(date(2026, 11, 1), scope=scope())
    assert result.out_of_period
