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


DEFAULT_BODY = object()  # 본문을 안 주면 자료마다 다른 본문 — 같은 본문은 중복으로 묶인다


def record(card_id: int, *, posted: datetime | None = None, body: str | None | object = DEFAULT_BODY,
           kind: str = "message", channel: str = "mock_ch") -> SourceRecord:
    posted = posted or CUTOFF - timedelta(hours=card_id)
    body = f"본문 {card_id}" if body is DEFAULT_BODY else body
    return SourceRecord(
        id=card_id, kind=kind, raw_id=card_id, title=None, url=f"https://t.me/{channel}/{card_id}",
        publisher="mock 채널", collection_path="telegram_web", channel=channel, published_at=posted,
        write_date=None, collected_at=posted, available_at=posted, has_body=body is not None,
        body_missing_reason=None if body is not None else "empty: 글자 없이 첨부만 올린 메시지",
        body_status="ok" if body is not None else "empty", body_error=None, body_fetched_at=posted,
        summary=None, body=body,
    )


def news_record(card_id: int, *, title: str | None = "제목", body: str | None | object = DEFAULT_BODY,
                publisher: str = "mock.news.com") -> SourceRecord:
    """네이버 기사. channel 이 없고 언론사·제목이 있다(read_model.news_record)."""
    rec = record(card_id, body=body, kind="news")
    rec.url, rec.title, rec.publisher, rec.channel = f"https://{publisher}/{card_id}", title, publisher, None
    rec.collection_path = "naver_news"
    return rec


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
        "text": "본문 10", "mention": "mentioned", "kind": "other", "after_prev_close": False,
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


def pdf_record(card_id: int, *, body: str | None | object = DEFAULT_BODY) -> SourceRecord:
    """네이버 리서치 리포트. 시각 없이 작성일만 있고 증권사·제목이 있다(read_model.pdf_record)."""
    rec = record(card_id, body=body, kind="pdf")
    rec.url, rec.title, rec.publisher, rec.channel = f"https://mock.research/{card_id}.pdf", "리포트 제목", "mock증권", None
    rec.published_at = rec.available_at = None
    rec.write_date = date(2026, 11, 2)
    return rec


def disclosure_record(card_id: int, *, title: str | None = "주요사항보고서(자기주식취득결정)") -> SourceRecord:
    """DART 공시. 본문 없이 제목·제출인·접수일만 있다(read_model.disclosure_record)."""
    rec = record(card_id, body=None, kind="disclosure")
    rec.url, rec.title, rec.publisher, rec.channel = f"https://dart.mock/{card_id}", title, "mock전자", None
    rec.published_at = rec.available_at = None
    rec.write_date = date(2026, 11, 3)
    rec.body_missing_reason = "not_collected: 공시는 목록(제목·제출인·접수일)만 저장한다"
    return rec


def test_pdf_and_disclosure_cards_go_in_and_missing_bodies_are_left_out():
    sources = [source(11, event("company"), card_type="pdf"), source(12, event("company")),
               source(13, event("company")), source(14, event("company"), card_type="pdf"),
               ci.disclosure_source(10), ci.disclosure_source(15)]
    records = [pdf_record(11), record(12, body=None), record(13), pdf_record(14, body=None),
               disclosure_record(10), disclosure_record(15, title=None)]
    payload, meta = build(sources, records)

    assert [(m["url"], m["channel"], m["kind"], m["mention"], m["datetime_kst"], m["text"])
            for m in payload["messages"]] == [
        ("https://mock.research/11.pdf", "mock증권", "other", "mentioned", "2026-11-02", "리포트 제목\n\n본문 11"),
        ("https://t.me/mock_ch/13", "mock_ch", "other", "mentioned", "2026-11-03T02:30:00+09:00", "본문 13"),
        ("https://dart.mock/10", "mock전자", "disclosure", "mentioned", "2026-11-03",
         "주요사항보고서(자기주식취득결정)"),
    ]
    assert meta["counts"]["skipped_card_types"] == {}
    assert (meta["counts"]["pdf"], meta["counts"]["disclosure"]) == (1, 1)
    assert meta["counts"]["no_body"] == 3
    assert [d["source_card_id"] for d in meta["dropped"]] == [12, 14, 15]
    assert (meta["unclassified"], meta["failed"], meta["not_observed"]) == (4, 1, 2)
    assert [m["kind"] for m in split_messages(payload)["messages"]] == ["other", "other", "disclosure"]


@pytest.mark.parametrize(("title", "expected"), [
    ("[기재정정]주식소각결정", True),
    ("[첨부정정]주요사항보고서(자기주식취득결정)", True),
    ("[첨부추가]투자설명서", True),
    ("[발행조건확정]증권신고서(채무증권)", False),   # 새 결정이라 정정이 아니다
    ("[연장결정]자기주식취득결정", False),
    ("주식소각결정", False),
    ("주요사항보고서(정정 전 내용 포함)", False),   # 머리 괄호가 아니면 정정이 아니다
    (None, False),
])
def test_is_correction(title, expected):
    assert ci.is_correction(title) is expected


def test_disclosure_messages_carry_is_correction_and_model_gets_it():
    sources = [source(10, event("company")), ci.disclosure_source(11), ci.disclosure_source(12)]
    records = [record(10), disclosure_record(11, title="[기재정정]주식소각결정"), disclosure_record(12)]
    payload, _ = build(sources, records)
    by_url = {m["url"]: m for m in payload["messages"]}
    assert "is_correction" not in by_url["https://t.me/mock_ch/10"]   # 공시에만 있다
    assert by_url["https://dart.mock/11"]["is_correction"] is True
    assert by_url["https://dart.mock/12"]["is_correction"] is False
    sent = {m["url"]: m for m in model_input(payload)["messages"]}
    assert sent["https://dart.mock/11"]["is_correction"] is True
    assert check_input(payload) == []


def test_news_cards_become_news_messages():
    sources = [source(13, event("company"), card_type="news"), source(12, event("industry"), card_type="news"),
               source(11, event("macro", None), card_type="news"), source(10, event("company"), card_type="news"),
               source(9, event("company"), card_type="news"), source(8, event("company"))]
    records = [news_record(13, title="SK하이닉스 中공장 장비 반입 보류", body="미 상무부가 승인하지 않고 있다."),
               news_record(12), news_record(11), news_record(10, title=None), news_record(9, body=None),
               record(8)]
    payload, meta = build(sources, records)

    first = payload["messages"][0]
    assert set(first) == MESSAGE_KEYS
    assert {k: first[k] for k in ("channel", "url", "text", "mention", "kind")} == {
        "channel": "mock.news.com", "url": "https://mock.news.com/13",
        "text": "SK하이닉스 中공장 장비 반입 보류\n\n미 상무부가 승인하지 않고 있다.",
        "mention": "mentioned", "kind": "news",
    }
    # mention·공통 배경 규칙은 메시지와 같다. 제목이 없으면 본문만
    assert [(m["url"].rsplit("/", 1)[1], m["mention"], m["kind"], m["text"]) for m in payload["messages"][1:]] == [
        ("12", "not_mentioned", "news", "제목\n\n본문 12"),
        ("11", "not_mentioned", "market_recap", "제목\n\n본문 11"),
        ("10", "mentioned", "news", "본문 10"),
        ("8", "mentioned", "other", "본문 8"),
    ]
    assert [m["card_type"] for m in meta["messages"]] == ["news"] * 4 + ["message"]
    assert meta["counts"]["news"] == 4
    assert meta["counts"]["skipped_card_types"] == {}
    assert meta["dropped"] == [{"source_card_id": 9, "reason": "empty: 글자 없이 첨부만 올린 메시지"}]
    assert [m["kind"] for m in split_messages(payload)["messages"]] == ["news", "news", "news", "other"]


@pytest.mark.parametrize(("telegram_body", "article_body", "representative", "kind"), [
    # 기사 본문만 옮긴 메시지와도 묶인다(제목은 비교에서 뺀다). 제목까지 있는 기사가 더 길어 대표
    ("기사 본문을 그대로 옮긴 글", "기사 본문을 그대로 옮긴 글", "10", "news"),
    # 텔레그램이 대표면 kind 는 other — 공통 배경 메시지라도 묶음에 근거 칸 기사가 있으니 근거 칸이다
    ("기사 본문을 그대로 옮긴 아주 긴 글 전체 내용입니다", "기사 본문을…", "11", "other"),
])
def test_message_and_article_with_same_body_are_grouped(telegram_body, article_body, representative, kind):
    sources = [source(11, event("macro", None)), source(10, event("company"), card_type="news")]
    payload, meta = build(sources, [record(11, body=telegram_body), news_record(10, body=article_body)])

    assert [(m["url"].rsplit("/", 1)[1], m["mention"], m["kind"], m["dup_channels"])
            for m in payload["messages"]] == [(representative, "mentioned", kind, 2)]
    assert meta["counts"]["news"] == (1 if kind == "news" else 0)
    assert meta["counts"]["duplicates"] == 1


def test_bundle_slot():
    before = (SINCE - timedelta(hours=3)).isoformat()
    after = (SINCE + timedelta(hours=1)).isoformat()
    payload, _ = build([
        source(10, event("company"), bundle={"first_seen_at": before, "dup_channels": 3}),
        source(11, event("company"), bundle={"first_seen_at": after, "dup_channels": 2}),
    ])
    assert [(m["first_seen_kst"], m["dup_channels"]) for m in payload["messages"]] == [
        ("2026-11-02T12:30:00+09:00", 3), (None, 2)]


# ── 중복 묶기 ─────────────────────────────────────────────────────────────

LONG = "[메리츠 반도체] 삼성전자: 확실한 저평가\n\n- 영업이익 107.4조원\n\n- 주주환원 계획 발표"


@pytest.mark.parametrize(("a", "b", "same"), [
    ("같은 글", "같은 글", True),
    ("줄 바꿈\n\n과 공백", "줄 바꿈  과   공백", True),                       # 공백은 한 칸으로 줄여 비교
    ("[메리츠 반도체] 삼성전자: 확실한 저평가 - 영업이익…", LONG, True),     # 「…」 뗀 나머지가 앞부분
    (LONG, "[메리츠 반도체] 삼성전자: 확실한 저평가 - 영업이익 …", True),     # 순서와 「…」 앞 공백은 상관없다
    ("[메리츠 반도체] 삼성전자: 확실한 저평가", LONG, False),                # 「…」 가 없으면 앞부분이어도 다른 글
    ("…", LONG, False),                                                       # 「…」 만 있는 글
    ("[메리츠 반도체] 삼성전자: 확실한 고평가…", LONG, False),
])
def test_same_text(a, b, same):
    assert ci.same_text(a, b) is same


def test_group_duplicates_is_transitive():
    texts = ["A 글 전체 본문", "다른 글", "A 글…", "A 글 전체…"]
    assert ci.group_duplicates(texts) == [[0, 2, 3], [1]]


@pytest.mark.parametrize("texts", [
    ["삼성전자…", "삼성전자 3분기 실적 발표 영업이익 증가", "삼성전자 노조 파업 돌입"],
    ["[속보]…", "[속보] A사 유상증자 결정", "[속보] B사 자사주 소각"],
    ["삼성전자 3분기 실적 발표 영업이익 증가", "삼성전자…", "삼성전자 노조…", "삼성전자 노조 파업 돌입"],
])
def test_cut_prefix_does_not_bridge_different_texts(texts):
    """「…」 앞부분이 서로 다른 글들의 앞부분이면 어느 쪽인지 모른다. 묶으면 다른 글이 중복으로 빠진다."""
    groups = ci.group_duplicates(texts)
    different = [i for i, t in enumerate(texts) if not t.endswith("…")]
    assert all(sum(i in g for i in different) <= 1 for g in groups)


def test_cut_prefix_still_groups_one_chain():
    texts = ["A사 유상증자…", "A사 유상증자 결정 공시…", "A사 유상증자 결정 공시 전문", "B사 자사주 소각"]
    assert ci.group_duplicates(texts) == [[0, 1, 2], [3]]


def test_short_cut_message_keeps_unrelated_news():
    """build_input 에서 보면: 짧게 잘린 메시지 하나 때문에 실적 기사와 파업 기사 중 하나가 「중복」으로 빠지면 안 된다."""
    sources = [source(13, event("company")), source(12, event("company")), source(11, event("company"))]
    records = [record(13, body="삼성전자…"), record(12, body="삼성전자 3분기 실적 발표 영업이익 증가"),
               record(11, body="삼성전자 노조 파업 돌입")]
    payload, meta = build(sources, records)
    texts = [m["text"] for m in payload["messages"]]
    assert "삼성전자 3분기 실적 발표 영업이익 증가" in texts and "삼성전자 노조 파업 돌입" in texts
    assert meta["counts"]["duplicates"] == 0


def test_duplicates_keep_longest_and_count_channels():
    cut = "[메리츠 반도체] 삼성전자: 확실한 저평가 - 영업이익…"
    sources = [source(13, event("industry")), source(12, event("company")), source(11, event("industry")),
               source(10, event("company"))]
    records = [record(13, body="같은 글", channel="ch_a"), record(12, body="같은 글", channel="ch_b"),
               record(11, body=LONG, channel="ch_a"), record(10, body=cut, channel="ch_a")]
    payload, meta = build(sources, records)

    # 같은 길이면 먼저 나온 글(13)이 대표. mention 은 묶음 중 하나라도 company 경로면 mentioned
    assert [(m["url"], m["mention"], m["dup_channels"]) for m in payload["messages"]] == [
        ("https://t.me/ch_a/13", "mentioned", 2),   # ch_a · ch_b
        ("https://t.me/ch_a/11", "mentioned", 1),   # 가장 긴 글이 대표. 같은 채널끼리라 1
    ]
    assert payload["messages"][1]["text"] == LONG
    assert [m["duplicates"] for m in meta["messages"]] == [[12], [10]]
    assert meta["counts"]["duplicates"] == 2
    assert meta["counts"]["messages"] == 2
    assert meta["dropped"] == [{"source_card_id": 12, "reason": "중복 — 대표 자료 13"},
                               {"source_card_id": 10, "reason": "중복 — 대표 자료 11"}]


def test_duplicate_of_evidence_stays_in_evidence_and_recap_limit_counts_after_grouping():
    sources = [source(n, event("macro", None)) for n in (16, 15, 14, 13, 12)]
    sources.append(source(11, event("company")))
    records = [record(16), record(15), record(14, body="시황"), record(13, body="시황"),
               record(12, body="시황 둘"), record(11, body="시황 둘")]
    payload, meta = build(sources, records)

    split = split_messages(payload)
    assert [m["url"].rsplit("/", 1)[1] for m in split["messages"]] == ["12"]    # 근거 칸 글과 묶이면 근거 칸
    # 공통 배경 4건(16·15·14·13)이 묶여서 3건 — 상한 3 안이라 다 남는다
    assert [m["url"].rsplit("/", 1)[1] for m in split["market_context"]] == ["16", "15", "14"]
    assert meta["counts"]["market_recap_dropped"] == 0
    assert meta["counts"]["duplicates"] == 2


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
        return found(source(10, event("company")), source(11, event("company"), card_type="news"),
                     source(12, event("company"), card_type="pdf"))

    async def fake_linked(session, code, *, until, since, card_type=None):
        seen["linked"] = (code, until, since)
        # 공시만 조회에서 고른다. 이어진 카드 전부(메시지 10·14 포함)를 읽고 거르지 않는다
        assert card_type == "disclosure"
        return [13]

    async def fake_sources(session, ids, *, include_body=False, cutoff=None):
        # 본문을 읽는 한 번뿐이다. 공시를 고르려고 이어진 카드를 get_sources 로 다시 읽지 않는다
        assert include_body, "공시를 고르려고 이어진 카드 전부를 get_sources 로 읽었다"
        seen["sources"] = (ids, include_body, cutoff)
        return [record(10), news_record(11), pdf_record(12), disclosure_record(13)]

    monkeypatch.setattr(ci, "classified_sources", fake_classified)
    monkeypatch.setattr(ci, "stock_card_ids", fake_linked)
    monkeypatch.setattr(ci, "get_sources", fake_sources)
    payload, meta = asyncio.run(ci.load_input(FakeSession(rows), CODE, cutoff=CUTOFF, change_pct=-1.2))

    assert seen["classified"] == seen["linked"] == (CODE, CUTOFF, since)
    # 메시지·뉴스·리포트·공시 카드, 본문 포함, 기준 시각으로 가림
    assert seen["sources"] == ([10, 11, 12, 13], True, CUTOFF)
    assert meta["since_basis"] == basis
    assert meta["since"] == since.isoformat()
    assert [m["kind"] for m in payload["messages"]] == ["other", "news", "other", "disclosure"]


def test_load_input_uses_given_since(monkeypatch):
    async def fake_classified(session, code, *, until, since):
        assert since == SINCE
        return found()

    async def fake_linked(session, code, *, until, since, card_type=None):
        assert since == SINCE and card_type == "disclosure"
        return []

    async def fake_sources(session, ids, *, include_body=False, cutoff=None):
        return []

    monkeypatch.setattr(ci, "classified_sources", fake_classified)
    monkeypatch.setattr(ci, "stock_card_ids", fake_linked)
    monkeypatch.setattr(ci, "get_sources", fake_sources)
    _, meta = asyncio.run(ci.load_input(FakeSession(None), CODE, cutoff=CUTOFF, change_pct=0.0, since=SINCE))
    assert meta["since_basis"] == "argument"


class NoDbSession:
    """종목표 검사가 DB 보다 먼저인지 본다. 어떤 조회든 오면 실패한다."""

    async def execute(self, *args, **kwargs):
        raise AssertionError("종목표에 없는 종목인데 DB 를 읽었다")

    def begin_nested(self):
        raise AssertionError("종목표에 없는 종목인데 DB 를 읽었다")


def test_load_input_checks_stock_table_before_db():
    with pytest.raises(ci.UnknownStockError, match="stock_meta.json 에 없는 종목: 035720"):
        asyncio.run(ci.load_input(NoDbSession(), "035720", cutoff=CUTOFF, change_pct=0.0))


def test_cli_unknown_stock_exits_1_with_guidance_and_no_traceback(monkeypatch, capsys):
    async def must_not_run(args):
        raise AssertionError("DB 를 여는 main 까지 가면 안 된다")

    monkeypatch.setattr(ci, "main", must_not_run)
    with pytest.raises(SystemExit) as info:
        ci.cli(["--code", "035720", "--cutoff", "2026-11-05T15:30:00+09:00", "--change-pct", "0"])
    assert info.value.code == 1
    err = capsys.readouterr().err
    assert "stock_meta.json 에 없는 종목: 035720" in err and "Traceback" not in err


def test_cli_known_stock_goes_on_to_main(monkeypatch):
    seen = []

    async def fake_main(args):
        seen.append(args.code)

    monkeypatch.setattr(ci, "main", fake_main)
    ci.cli(["--code", CODE, "--cutoff", "2026-11-05T15:30:00+09:00", "--change-pct", "1.5"])
    assert seen == [CODE]
