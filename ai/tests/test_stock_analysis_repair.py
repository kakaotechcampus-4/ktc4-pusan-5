"""quote 고쳐 쓰기(repair)·main_cause 다시 쓰기와 issue_trace 검사. complete() 를 바꿔 끼워 API 를 부르지 않는다."""

import json
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError
from app.services.stock_analysis import repair
from app.services.stock_analysis.verify import (
    ISSUE_ID_UNKNOWN,
    ISSUE_TRACE_MISSING_URL,
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


def test_issue_not_in_any_event_is_not_warned_but_counted():
    """events 는 실제로 적은 사건만 담는다. 어느 사건에도 들지 않은 이슈는 issue_trace 에만 남고 경고가 아니다."""
    r = {"events": [{"issue_ids": ["i1"]}]}
    t = trace(("i1", "direct"), ("i2", "sector"), ("i3", "market"))
    assert check_issue_trace(t, r) == []
    assert issue_trace_stats(t, r, {"messages": [{"url": URL}]})["issues_used"] == 1


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


def test_issue_trace_stats_relations_and_used():
    t = trace(("i1", "direct"), ("i2", "market"), ("i3", "market"))
    r = {"events": [{"issue_ids": ["i1", "i2"]}]}
    assert check_issue_trace(t, r, {"messages": [{"url": URL}]}) == []
    stats = issue_trace_stats(t, r, {"messages": [{"url": URL}]})
    assert stats["issues_used"] == 2
    assert stats["relations"] == {"direct": 1, "market": 2}
    assert issue_trace_stats(None, r, {"messages": []}) is None


def test_issue_trace_by_message_id():
    """issue_trace 는 messages 칸 id(m1…)로 적는다. 빠진 id 는 'id url' 로 경고한다."""
    payload = {"messages": [{"url": URL, "kind": "news"}, {"url": "https://t.me/ch/2", "kind": "market_recap"},
                            {"url": "https://t.me/ch/3", "kind": "news"}, {"url": "https://t.me/ch/4", "kind": "other"}]}
    t = [{"id": "m1", "issues": [{"id": "i1", "issue": "x", "relation": "direct"}], "none_count": 0},
         {"id": "m3", "issues": [], "none_count": 2}]   # m2 는 ch/3 (시황 ch/2 는 칸 밖이라 번호가 없다)
    r = {"events": [{"issue_ids": ["i1"]}]}
    warnings = check_issue_trace(t, r, payload)
    assert [code_of(w) for w in warnings] == [ISSUE_TRACE_MISSING_URL]
    assert "m2 https://t.me/ch/3" in warnings[0]
    stats = issue_trace_stats(t, r, payload)
    assert (stats["messages_traced"], stats["messages_total"]) == (2, 3)


def test_issue_trace_only_covers_messages_column():
    """market_context(시장 시황·전날 장 설명)와 flow(매매 순위)는 issue_trace 대상이 아니라 누락으로 세지 않는다."""
    payload = {"messages": [{"url": URL, "kind": "news"},
                            {"url": "https://t.me/ch/2", "kind": "market_recap"},
                            {"url": "https://t.me/ch/3", "kind": "theme_recap", "after_prev_close": True},
                            {"url": "https://t.me/ch/4", "kind": "flow_rank"}]}
    r = {"events": [{"issue_ids": ["i1"]}]}
    assert check_issue_trace(trace(("i1", "direct")), r, payload) == []
    stats = issue_trace_stats(trace(("i1", "direct")), r, payload)
    assert (stats["messages_traced"], stats["messages_total"]) == (1, 1)


def test_none_issues_are_counted_from_none_count():
    """none 이슈는 issues 에 적지 않고 메시지마다 none_count 만 남긴다. url 은 남아 누락 검사가 그대로 돈다."""
    payload = {"messages": [{"url": URL}, {"url": "https://t.me/ch/2"}]}
    t = trace(("i1", "direct")) + [{"url": "https://t.me/ch/2", "issues": [], "none_count": 4}]
    t[0]["none_count"] = 2
    r = {"events": [{"issue_ids": ["i1"]}]}
    assert check_issue_trace(t, r, payload) == []
    assert issue_trace_stats(t, r, payload)["relations"] == {"direct": 1, "none": 6}


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


def bg_report(quote, counter="반대 재료가 있었습니다."):
    r = report("규제 대상 장비로 명시")  # factor 는 둘 다 통과
    r["summary"] = {"main_cause": "c", "counter": counter}
    r["background"] = {"bullish": [], "neutral": [],
                       "bearish": [{"text": "행정명령", "sources": [source(quote)], "watch": True}]}
    r["events"].append({"event": "행정명령 배경", "issue_ids": ["i3"], "dup_channels": None,
                        "placed": "background", "background": {"slot": "bearish", "index": 0}})
    return r


async def test_background_quote_is_rewritten_and_keeps_watch(fake_complete):
    r = bg_report("규제 대상으로 장비로 명시")
    fake_complete.return_value = (json.dumps(
        {"text": "행정명령이 BESS 를 규제 대상으로 명시했습니다.", "sources": [source("규제 대상 장비로 명시")]}), USAGE)
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert [(x["kind"], x["path"], x["result"]) for x in records] == [
        ("background", "background.bearish[0]", "fixed")]
    item = r["background"]["bearish"][0]
    assert item["sources"][0]["quote"] == "규제 대상 장비로 명시" and item["watch"] is True
    assert fake_complete.await_args.args[0] == repair.BACKGROUND_REPAIR_SYSTEM


async def test_background_second_failure_drops_item_clears_counter_and_passes(fake_complete):
    from app.services.stock_analysis.verify import check_grounding, check_rules

    r = bg_report("규제 대상으로 장비로 명시")
    fake_complete.return_value = (json.dumps({"text": "x", "sources": [source("여전히 없는 문장")]}), USAGE)
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert records[0]["result"] == "dropped" and records[0]["counter_cleared"] is True
    assert r["background"]["bearish"] == []
    assert r["summary"]["counter"] is None
    # 그 항목을 가리키던 사건을 dropped 로 바꾼다. 사건을 새로 더하지 않는다
    assert r["events"][-1] == {"event": "행정명령 배경", "issue_ids": ["i3"], "dup_channels": None,
                               "placed": "dropped", "reason": QUOTE_VERIFY_FAIL}
    assert check_events(r) == ("passed", [])
    assert check_grounding(r, PAYLOAD) == []
    assert "COUNTER_WITHOUT_BACKGROUND" not in {code_of(p) for p in check_rules(r, {"change_pct": 2.0})}


async def test_counter_is_kept_when_other_background_items_remain(fake_complete):
    r = bg_report("규제 대상으로 장비로 명시")
    r["background"]["neutral"].append({"text": "다른 재료", "sources": [source("BESS를 규제 대상 장비로")]})
    fake_complete.side_effect = LLMError("HTTP 500")
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert records[0]["result"] == "dropped" and "counter_cleared" not in records[0]
    assert r["summary"]["counter"] == "반대 재료가 있었습니다."
    assert len(r["background"]["neutral"]) == 1


async def test_background_drops_keep_slot_indexes_right(fake_complete):
    r = bg_report("없는 문장 하나")
    r["background"]["bearish"] += [{"text": "가운데", "sources": [source("BESS를 규제 대상 장비로")]},
                                   {"text": "끝", "sources": [source("없는 문장 둘")]}]
    fake_complete.side_effect = LLMError("HTTP 500")
    records = await repair.repair_quotes(r, PAYLOAD, stream=True)
    assert [x["path"] for x in records] == ["background.bearish[0]", "background.bearish[2]"]
    assert [x["text"] for x in r["background"]["bearish"]] == ["가운데"]


async def test_background_drop_moves_event_indexes(fake_complete):
    """뺀 항목을 가리키던 사건은 dropped 가 되고, 같은 칸 뒤 항목을 가리키던 사건은 순번이 당겨진다."""
    r = bg_report("없는 문장 하나")
    r["background"]["bearish"].append({"text": "끝", "sources": [source("BESS를 규제 대상 장비로")]})
    r["background"]["neutral"].append({"text": "다른 칸", "sources": [source("BESS를 규제 대상 장비로")]})
    r["events"] += [{"event": "끝", "issue_ids": [], "dup_channels": None, "placed": "background",
                     "background": {"slot": "bearish", "index": 1}},
                    {"event": "다른 칸", "issue_ids": [], "dup_channels": None, "placed": "background",
                     "background": {"slot": "neutral", "index": 0}}]
    fake_complete.side_effect = LLMError("HTTP 500")
    await repair.repair_quotes(r, PAYLOAD, stream=True)
    by_event = {e["event"]: e for e in r["events"]}
    assert by_event["행정명령 배경"]["placed"] == "dropped" and "background" not in by_event["행정명령 배경"]
    assert by_event["끝"]["background"] == {"slot": "bearish", "index": 0}
    assert by_event["다른 칸"]["background"] == {"slot": "neutral", "index": 0}
    assert check_events(r) == ("passed", [])
