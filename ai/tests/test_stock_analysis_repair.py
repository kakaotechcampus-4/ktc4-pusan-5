"""quote 고쳐 쓰기(repair)와 issue_trace 참조 검사. complete() 를 바꿔 끼워 API 를 부르지 않는다."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.stock_analysis import repair
from app.services.stock_analysis.verify import (
    ISSUE_ID_UNKNOWN,
    ISSUE_UNREFERENCED,
    QUOTE_VERIFY_FAIL,
    check_events,
    check_issue_trace,
    code_of,
)

URL = "https://t.me/ch/1"
PAYLOAD = {"messages": [{"channel": "ch", "url": URL, "datetime_kst": "2026-10-14T11:40:00+09:00",
                         "match": "indirect", "text": "미국의 전력망 보안 행정명령은 BESS를 규제 대상 장비로 명시"}]}
USAGE = {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.5, "finish_reason": "stop"}


def source(quote):
    return {"channel": "ch", "url": URL, "datetime_kst": "2026-10-14T11:40:00+09:00",
            "quote": quote, "match": "indirect", "is_market_recap": False}


def report(quote):
    good = {"event": "다른 사건", "detail": "", "stance": "bullish", "unconfirmed": False,
            "sources": [source("BESS를 규제 대상 장비로")], "links": [{"layer": "move"}]}
    bad = {"event": "행정명령", "detail": "", "stance": "bullish", "unconfirmed": False,
           "sources": [source(quote)], "links": [{"layer": "move", "strength": "partial"}]}
    return {"factors": [bad, good],
            "events": [{"event": "행정명령", "issue_ids": ["i1"], "factor": 0, "dup_channels": None,
                        "placed": "factors"},
                       {"event": "다른 사건", "issue_ids": ["i2"], "factor": 1, "dup_channels": None,
                        "placed": "factors"}]}


@pytest.fixture
def fake_complete(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(repair, "complete", mock)
    return mock


async def test_passing_quotes_are_not_rewritten(fake_complete):
    r = report("규제 대상 장비로 명시")
    assert await repair.repair_quotes(r, PAYLOAD, stream=True) == []
    fake_complete.assert_not_called()


async def test_rewrite_fixes_quote_and_keeps_links(fake_complete):
    r = report("규제 대상으로 장비로 명시")
    fake_complete.return_value = (json.dumps(
        {"event": "행정명령", "detail": "", "sources": [source("규제 대상 장비로 명시")]}), USAGE)
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert [x["result"] for x in records] == ["fixed"]
    assert r["factors"][0]["sources"][0]["quote"] == "규제 대상 장비로 명시"
    assert r["factors"][0]["links"] == [{"layer": "move", "strength": "partial"}]
    assert fake_complete.await_count == 1


async def test_second_failure_drops_factor_and_marks_event(fake_complete):
    r = report("규제 대상으로 장비로 명시")
    fake_complete.return_value = (json.dumps(
        {"event": "행정명령", "detail": "", "sources": [source("여전히 없는 문장")]}), USAGE)
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert [x["result"] for x in records] == ["dropped"]
    assert [f["event"] for f in r["factors"]] == ["다른 사건"]
    assert r["events"][0] == {"event": "행정명령", "issue_ids": ["i1"], "dup_channels": None,
                              "placed": "dropped", "reason": QUOTE_VERIFY_FAIL}
    assert r["events"][1]["factor"] == 0  # 뒤 factor 의 순번이 당겨진다
    assert check_events(r) == ("passed", [])


async def test_unreadable_rewrite_drops_factor(fake_complete):
    r = report("규제 대상으로 장비로 명시")
    fake_complete.return_value = ("고칠 수 없습니다", USAGE)
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert records[0]["result"] == "dropped" and records[0]["error"]


def trace(*issues):
    return [{"url": URL, "issues": [{"id": i, "issue": i, "relation": rel} for i, rel in issues]}]


def test_issue_trace_unreferenced_related_issue_warns():
    r = {"events": [{"issue_ids": ["i1"]}]}
    warnings = check_issue_trace(trace(("i1", "direct"), ("i2", "sector"), ("i3", "none")), r)
    assert [code_of(w) for w in warnings] == [ISSUE_UNREFERENCED]
    assert "'i2'" in warnings[0]


def test_issue_trace_unknown_id_and_missing_trace():
    r = {"events": [{"issue_ids": ["i1", "i9"]}]}
    assert [code_of(w) for w in check_issue_trace(trace(("i1", "direct")), r)] == [ISSUE_ID_UNKNOWN]
    assert check_issue_trace(None, r) == []
    assert check_issue_trace(trace(("i1", "direct")), None) == []
