"""분류 결과 → 러너 입력 어댑터. DB·LLM 을 쓰지 않는다(classified_sources·get_sources·세션을 바꿔 끼운다)."""

import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import ProgrammingError

from app.collectors.stock_analysis import collect_inputs
from app.core.scope import KST
from app.repositories.source_card.read_model import SourceRecord
from app.services.stock_analysis import classified_input as ci
from app.services.stock_analysis.generate import check_input, model_input, needs_llm
from app.services.stock_analysis.verify import split_messages

CODE = "005930"
CUTOFF = datetime(2026, 11, 3, 15, 30, tzinfo=KST)  # 화요일
SINCE = datetime(2026, 11, 2, 15, 30, tzinfo=KST)
MESSAGE_KEYS = {"channel", "url", "datetime_kst", "text", "mention", "kind", "after_prev_close",
                "first_seen_kst", "dup_channels"}


def record(card_id: int, *, posted: datetime | None = None, body: str | None = "본문",
           kind: str = "message") -> SourceRecord:
    posted = posted or CUTOFF - timedelta(hours=card_id)
    return SourceRecord(
        id=card_id, kind=kind, raw_id=card_id, title=None, url=f"https://t.me/mock_ch/{card_id}",
        publisher="mock 채널", collection_path="telegram_web", channel="mock_ch", published_at=posted,
        write_date=None, collected_at=posted, available_at=posted, has_body=body is not None,
        body_missing_reason=None if body is not None else "empty: 글자 없이 첨부만 올린 메시지",
        body_status="ok" if body is not None else "empty", body_error=None, body_fetched_at=posted,
        summary=None, body=body,
    )


def event(path: str, label: str | None = "DIRECT") -> dict:
    scope = path if path in ("macro", "market") else "company"
    return {"event_id": 1, "run_id": 1, "scope": scope, "role": "cause", "tense": "past",
            "sentence_indices": [1], "context_indices": [], "label": label, "path": path}


def source(card_id: int, *events: dict, card_type: str = "message", **extra) -> dict:
    labels = [e["label"] for e in events if e["label"]]
    order = ("DIRECT", "INDIRECT_CONTEXT", "UNKNOWN", "NOT_APPLICABLE")
    return {"source_card_id": card_id, "card_type": card_type, "source_name": "mock", "url": None,
            "channel_id": 1, "available_at": None, "body_status": "ok",
            "card_label": min(labels, key=order.index) if labels else None,
            "events": list(events), **extra}


def found(*sources: dict) -> dict:
    return {"sources": list(sources), "unclassified": 4, "failed": 1, "not_observed": 2}


def build(sources: list[dict], records: list[SourceRecord] | None = None):
    records = records if records is not None else [record(s["source_card_id"]) for s in sources]
    return ci.build_input(found(*sources), {r.id: r for r in records}, code=CODE, cutoff=CUTOFF,
                          change_pct=-1.2, since=SINCE)


# ── 메시지 칸 ─────────────────────────────────────────────────────────────

def test_mention_follows_company_path_not_label():
    payload, _ = build([
        source(10, event("company", "INDIRECT_CONTEXT")),  # 판정과 상관없이 company 경로면 mentioned
        source(11, event("industry", "DIRECT")),           # card_label 이 DIRECT 여도 industry 면 not_mentioned
        source(12, event("relation", "INDIRECT_CONTEXT"), event("macro", None)),
    ])
    assert [m["mention"] for m in payload["messages"]] == ["mentioned", "not_mentioned", "not_mentioned"]
    assert [m["kind"] for m in payload["messages"]] == ["other"] * 3


def test_message_fields_and_defaults():
    payload, _ = build([source(10, event("company"))])
    message = payload["messages"][0]
    assert set(message) == MESSAGE_KEYS  # views·link_bodies 는 넣지 않는다
    assert message == {
        "channel": "mock_ch", "url": "https://t.me/mock_ch/10", "datetime_kst": "2026-11-03T05:30:00+09:00",
        "text": "본문", "mention": "mentioned", "kind": "other", "after_prev_close": False,
        "first_seen_kst": None, "dup_channels": 1,
    }
    assert {k: payload[k] for k in ("stock", "code", "target_date", "cutoff", "change_pct", "market")} == {
        "stock": "삼성전자", "code": CODE, "target_date": "2026-11-03",
        "cutoff": "2026-11-03T15:30:00+09:00", "change_pct": -1.2, "market": None,
    }


def test_datetime_falls_back_to_available_at():
    rec = record(10)
    rec.published_at = None
    payload, _ = build([source(10, event("company"))], [rec])
    assert payload["messages"][0]["datetime_kst"] == "2026-11-03T05:30:00+09:00"


def test_common_background_goes_to_market_context_and_keeps_latest_three():
    sources = [source(n, event("macro", None)) for n in (15, 14, 13, 12, 11)]  # 오래된 순(15시간 전 …)
    sources.insert(2, source(20, event("company"), event("market", None)))  # 회사 사건이 섞이면 근거 칸
    payload, meta = build(sources)

    assert [m["url"].rsplit("/", 1)[1] for m in payload["messages"]] == ["20", "13", "12", "11"]
    split = split_messages(payload)
    assert [m["url"] for m in split["messages"]] == ["https://t.me/mock_ch/20"]
    assert [m["kind"] for m in split["market_context"]] == ["market_recap"] * 3
    assert {m["mention"] for m in split["market_context"]} == {"not_mentioned"}
    assert meta["counts"]["market_recap_dropped"] == 2
    assert [d["source_card_id"] for d in meta["dropped"]] == [15, 14]


def test_non_message_cards_and_missing_bodies_are_left_out():
    sources = [source(10, event("company"), card_type="news"), source(11, event("company"), card_type="pdf"),
               source(12, event("company")), source(13, event("company"))]
    payload, meta = build(sources, [record(12, body=None), record(13)])
    assert [m["url"] for m in payload["messages"]] == ["https://t.me/mock_ch/13"]
    assert meta["counts"]["skipped_card_types"] == {"news": 1, "pdf": 1}
    assert meta["counts"]["no_body"] == 1
    assert meta["dropped"] == [{"source_card_id": 12, "reason": "empty: 글자 없이 첨부만 올린 메시지"}]
    assert (meta["unclassified"], meta["failed"], meta["not_observed"]) == (4, 1, 2)


def test_bundle_slot():
    before = (SINCE - timedelta(hours=3)).isoformat()
    after = (SINCE + timedelta(hours=1)).isoformat()
    payload, _ = build([
        source(10, event("company"), bundle={"first_seen_at": before, "dup_channels": 3}),
        source(11, event("company"), bundle={"first_seen_at": after, "dup_channels": 2}),
    ])
    assert [(m["first_seen_kst"], m["dup_channels"]) for m in payload["messages"]] == [
        ("2026-11-02T12:30:00+09:00", 3), (None, 2)]


def test_unknown_stock_is_an_error():
    with pytest.raises(ValueError, match="999999"):
        ci.build_input(found(), {}, code="999999", cutoff=CUTOFF, change_pct=0.0, since=SINCE)


def test_output_passes_runner_input_checks_and_model_gets_no_extra_keys():
    payload, _ = build([source(10, event("company")), source(11, event("macro", None))])
    assert check_input(payload) == []
    assert needs_llm(payload)
    sent = model_input(payload)
    assert set(sent["messages"][0]) == MESSAGE_KEYS | {"id"}
    assert set(sent["market_context"][0]) == MESSAGE_KEYS
    assert "source_card_id" not in str(sent)


def test_write_keeps_meta_out_of_runner_input_folder(tmp_path):
    payload, meta = build([source(10, event("company"))])
    path = ci.write(tmp_path, payload, meta)
    assert path.name == "005930-2026-11-03-1530.json"
    assert (tmp_path / "meta" / path.name).exists()
    assert collect_inputs(tmp_path) == [path]


# ── 조회 시작 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("day", "open_days", "expected"), [
    (date(2026, 11, 3), None, datetime(2026, 11, 2, 15, 30, tzinfo=KST)),       # 화 → 월
    (date(2026, 11, 2), None, datetime(2026, 10, 30, 15, 30, tzinfo=KST)),      # 월 → 금
    (date(2026, 11, 3), {date(2026, 11, 2): False}, datetime(2026, 10, 30, 15, 30, tzinfo=KST)),  # 월 휴장
    (date(2026, 11, 20), None, datetime(2026, 11, 19, 16, 30, tzinfo=KST)),     # LATE_CLOSE 날
    (date(2026, 11, 3), {d: False for d in (date(2026, 11, 3) - timedelta(days=n) for n in range(1, 31))},
     datetime(2026, 11, 2, 15, 30, tzinfo=KST)),                                # 한 달 휴장은 틀린 달력
])
def test_previous_close(day, open_days, expected):
    assert ci.previous_close(day, open_days) == expected


class FakeSession:
    """market_calendar 읽기만 흉내 낸다. rows 가 None 이면 표가 없는 것처럼 실패한다."""

    def __init__(self, rows):
        self.rows = rows

    def begin_nested(self):
        class Savepoint:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        return Savepoint()

    async def execute(self, statement, params=None):
        if self.rows is None:
            raise ProgrammingError("SELECT … market_calendar", params, Exception("relation does not exist"))

        class Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return Result(self.rows)


@pytest.mark.parametrize(("rows", "basis", "since"), [
    (None, "weekday_fallback", datetime(2026, 11, 2, 15, 30, tzinfo=KST)),
    ([], "weekday_fallback", datetime(2026, 11, 2, 15, 30, tzinfo=KST)),  # 표는 있지만 그 기간에 행이 없다
    ([(date(2026, 11, 2), False)], "market_calendar", datetime(2026, 10, 30, 15, 30, tzinfo=KST)),
])
def test_load_input_default_since(monkeypatch, rows, basis, since):
    seen = {}

    async def fake_classified(session, code, *, until, since):
        seen["classified"] = (code, until, since)
        return found(source(10, event("company")), source(11, event("company"), card_type="news"))

    async def fake_sources(session, ids, *, include_body, cutoff):
        seen["sources"] = (ids, include_body, cutoff)
        return [record(i) for i in ids]

    monkeypatch.setattr(ci, "classified_sources", fake_classified)
    monkeypatch.setattr(ci, "get_sources", fake_sources)
    payload, meta = asyncio.run(ci.load_input(FakeSession(rows), CODE, cutoff=CUTOFF, change_pct=-1.2))

    assert seen["classified"] == (CODE, CUTOFF, since)
    assert seen["sources"] == ([10], True, CUTOFF)  # 메시지 카드만, 본문 포함, 기준 시각으로 가림
    assert meta["since_basis"] == basis
    assert meta["since"] == since.isoformat()
    assert len(payload["messages"]) == 1


def test_load_input_uses_given_since(monkeypatch):
    async def fake_classified(session, code, *, until, since):
        assert since == SINCE
        return found()

    async def fake_sources(session, ids, *, include_body, cutoff):
        return []

    monkeypatch.setattr(ci, "classified_sources", fake_classified)
    monkeypatch.setattr(ci, "get_sources", fake_sources)
    _, meta = asyncio.run(ci.load_input(FakeSession(None), CODE, cutoff=CUTOFF, change_pct=0.0, since=SINCE))
    assert meta["since_basis"] == "argument"
