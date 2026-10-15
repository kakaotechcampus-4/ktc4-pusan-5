"""quote 고쳐 쓰기(repair)·main_cause 다시 쓰기와 issue_trace 검사. complete() 를 바꿔 끼워 API 를 부르지 않는다."""

import json
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError
from app.services.stock_analysis import repair
from app.services.stock_analysis.verify import (
    ISSUE_ID_UNKNOWN,
    ISSUE_TRACE_MISSING_URL,
    ISSUE_UNREFERENCED,
    QUOTE_VERIFY_FAIL,
    check_events,
    check_issue_trace,
    code_of,
    issue_trace_stats,
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


def test_issue_trace_missing_input_url_warns_and_is_counted():
    payload = {"messages": [{"url": URL}, {"url": "https://t.me/ch/2"}, {"url": "https://t.me/ch/3"}]}
    r = {"events": [{"issue_ids": ["i1"]}]}
    warnings = check_issue_trace(trace(("i1", "direct")), r, payload)
    assert [code_of(w) for w in warnings] == [ISSUE_TRACE_MISSING_URL] * 2
    assert "ch/2" in warnings[0] and "ch/3" in warnings[1]
    stats = issue_trace_stats(trace(("i1", "direct")), r, payload)
    assert (stats["messages_traced"], stats["messages_total"]) == (1, 3)


def test_market_issue_is_not_warned_but_counted_when_unreferenced():
    t = trace(("i1", "direct"), ("i2", "market"), ("i3", "market"))
    r = {"events": [{"issue_ids": ["i1", "i2"]}]}
    assert check_issue_trace(t, r, {"messages": [{"url": URL}]}) == []
    stats = issue_trace_stats(t, r, {"messages": [{"url": URL}]})
    assert stats["market_unreferenced"] == 1
    assert stats["relations"] == {"direct": 1, "market": 2}
    assert issue_trace_stats(None, r, {"messages": []}) is None


def cause_report():
    """factors[0] 은 quote 가 원문에 없는 move factor, factors[1] 은 멀쩡한 move factor."""
    r = report("규제 대상으로 장비로 명시")
    r["verdict"] = "explained"
    r["summary"] = {"main_cause": "행정명령과 다른 사건 때문입니다."}
    return r


def answers(*texts):
    return [(t, USAGE) for t in texts]


async def test_main_cause_is_rewritten_when_move_factor_is_dropped(fake_complete):
    r = cause_report()
    fake_complete.side_effect = answers(json.dumps({"event": "x", "sources": [source("없는 문장")]}),
                                        json.dumps({"main_cause": "다른 사건 때문입니다."}))
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert records[0]["layers"] == ["move"]
    rewrite = await repair.rewrite_main_cause(r, records, stream=True)
    assert rewrite["result"] == "rewritten"
    assert (rewrite["before"], rewrite["after"]) == ("행정명령과 다른 사건 때문입니다.", "다른 사건 때문입니다.")
    assert r["summary"]["main_cause"] == "다른 사건 때문입니다."
    # 남은 근거만 넘긴다. 뺀 factor 는 dropped 에 사건 이름만 간다.
    sent = json.loads(fake_complete.await_args_list[1].args[1])
    assert [f["event"] for f in sent["remaining_factors"]] == ["다른 사건"]
    assert sent["dropped"] == ["행정명령"]


@pytest.mark.parametrize("reply", [LLMError("HTTP 500"), ("다시 쓸 수 없습니다", USAGE)])
async def test_failed_main_cause_rewrite_keeps_text_and_reports_failure(fake_complete, reply):
    r = cause_report()
    fake_complete.side_effect = [(json.dumps({"event": "x", "sources": [source("없는 문장")]}), USAGE), reply]
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    rewrite = await repair.rewrite_main_cause(r, records, stream=True)
    assert rewrite["result"] == "failed" and rewrite["error"]
    assert r["summary"]["main_cause"] == "행정명령과 다른 사건 때문입니다."


async def test_main_cause_is_left_alone_without_dropped_move_factor(fake_complete):
    r = cause_report()
    r["factors"][0]["links"] = [{"layer": "relative", "strength": "partial"}]
    fake_complete.return_value = (json.dumps({"event": "x", "sources": [source("없는 문장")]}), USAGE)
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert records[0]["result"] == "dropped"
    assert await repair.rewrite_main_cause(r, records, stream=True) is None
    assert await repair.rewrite_main_cause(r, [], stream=True) is None
    assert fake_complete.await_count == 1
