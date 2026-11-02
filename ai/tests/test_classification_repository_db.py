"""분류 표 저장·제약·조회를 실제 PostgreSQL 에서 본다.

    - 기준 JSON 이 기준표 4개로 들어가고, 빠진 산업은 지우지 않고 은퇴시킨다
    - 회차 저장: 현재 회차 교체와 source_card_stocks(DIRECT) 갱신이 같이 일어난다
    - 실패·실험 회차는 조회에 쓰는 회차를 바꾸지 않는다
    - 종목별 조회는 판정 자료와 공통 배경(거시·시장)을 함께 낸다
    - CHECK 가 LLM 출력의 규칙 위반을 막고, 분류 회차가 있으면 downgrade 를 멈춘다
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from app.repositories.classification import (
    cards_to_classify,
    classified_sources,
    save_run,
    stored_basis_versions,
    sync_basis,
)
from app.repositories.news import save_news
from app.repositories.source_card import register_missing_sources
from app.services.classification import llm
from app.services.classification.basis import load_basis, parse_basis
from app.services.classification.pipeline import classify
from tests.db import in_session
from tests.test_migrations import alembic, query

MOCK_BASIS = Path(__file__).parent / "fixtures" / "mock_classification_basis.json"
BASIS = load_basis(MOCK_BASIS)
PUBLISHED = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)  # KST 09:00
UNTIL = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)

TITLE = "SK하이닉스, D램 가격 급등에 실적 기대"
BODY = "D램 가격이 급등했다. 회사는 3분기 실적 개선을 예고했다. 미국 금리가 내렸다."
EVENTS = {"events": [
    {"scope": "industry", "role": "cause", "tense": "past", "sentences": [1], "mentions": ["D램"]},
    {"scope": "company", "role": "outlook", "tense": "future", "sentences": [2], "context": [1],
     "mentions": ["SK하이닉스"]},
    {"scope": "macro", "role": "cause", "tense": "past", "sentences": [3], "mentions": ["미국 금리"]},
]}


def judgments(**labels: str) -> dict:
    """event 1 의 후보 셋과 event 2 의 후보 둘. 주지 않은 것은 INDIRECT_CONTEXT."""
    keys = [(1, "005930"), (1, "000660"), (1, "402340"), (2, "000660"), (2, "402340")]
    return {"judgments": [{"event": e, "stock": s, "label": labels.get(f"e{e}_{s}", "INDIRECT_CONTEXT"),
                           "reason": "mock"} for e, s in keys]}


def classify_with(monkeypatch, judged: dict, *, judge_error: bool = False):
    async def complete(system, user, **kwargs):
        if "# 판정할 사건" in user:
            if judge_error:
                raise llm.LLMError("LLM 호출 실패: HTTP 429")
            return json.dumps(judged), {"finish_reason": "stop"}
        return json.dumps(EVENTS, ensure_ascii=False), {"finish_reason": "stop"}

    monkeypatch.setattr(llm, "complete", complete)
    return asyncio.run(classify(TITLE, BODY, BASIS))


def setup(database: str) -> int:
    """head 까지 올리고 기준표를 넣고, 본문 있는 기사 카드 하나를 만든다. 카드 id 를 돌려준다."""
    alembic(database, "upgrade", "head")
    in_session(database, lambda s: sync_basis(s, BASIS))
    in_session(database, lambda s: save_news(s, [{
        "url": "https://news.example.com/a/1", "title": TITLE, "publisher": "news.example.com",
        "source": "naver", "published_at": PUBLISHED, "summary": "", "cleaned_text": BODY,
        "body_status": "ok", "body_error": None, "body_fetched_at": PUBLISHED,
        "body_extractor": "naver",
    }]))
    in_session(database, register_missing_sources)
    return query(database, "SELECT id FROM source_card WHERE card_type = 'news'")[0]["id"]


def save(database: str, card_id: int, result, **kwargs) -> int:
    return in_session(database, lambda s: save_run(s, card_id, result, **kwargs))


def tagged(database: str, card_id: int) -> set[str]:
    return {r["stock_code"] for r in query(
        database, "SELECT stock_code FROM source_card_stocks WHERE source_card_id = $1"
        " AND tagged_by = 'classification'", card_id)}


def test_basis_sync_counts_versions_and_retires(database):
    alembic(database, "upgrade", "head")
    counts = in_session(database, lambda s: sync_basis(s, BASIS))
    assert counts["industries"] == len(BASIS.industries)
    assert counts["company_relations"] == len(BASIS.relations)
    assert in_session(database, stored_basis_versions) == {BASIS.version}
    competitor = query(database, "SELECT from_stock_code, to_stock_code FROM company_relations"
                                 " WHERE relation_type = 'competitor' AND to_stock_code = '066570'")
    assert competitor[0]["from_stock_code"] == "005930"

    data = json.loads(MOCK_BASIS.read_text(encoding="utf-8"))
    data["industries"] = [i for i in data["industries"] if i["code"] != "home_appliance"]
    data["stock_industries"] = [x for x in data["stock_industries"] if x["industry"] != "home_appliance"]
    data["company_relations"] = [r for r in data["company_relations"]
                                 if r["industry"] != "home_appliance"]
    in_session(database, lambda s: sync_basis(s, parse_basis(data, version="v2")))
    row = query(database, "SELECT retired_at FROM industries WHERE code = 'home_appliance'")[0]
    assert row["retired_at"] is not None  # 과거 결과가 가리키므로 지우지 않는다
    assert in_session(database, stored_basis_versions) == {"v2"}


def test_cards_to_classify_since_compares_unknown_time_by_kst_date(database):
    """공개 시각을 모르는 자료는 since 의 KST 날짜로 판단한다(stock_card_ids 와 같은 규칙)."""
    card_id = setup(database)
    query(database, "UPDATE source_card SET available_at = NULL, event_date = '2026-10-27'"
                    " WHERE id = $1", card_id)
    kst_1028 = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)  # KST 10-28 01:00
    kst_1027 = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)  # KST 10-27 01:00
    assert in_session(database, lambda s: cards_to_classify(s, since=kst_1028)) == []
    assert in_session(database, lambda s: cards_to_classify(s, since=kst_1027)) == [card_id]


def test_save_run_makes_current_and_indexes_direct(database, monkeypatch):
    card_id = setup(database)
    assert in_session(database, lambda s: cards_to_classify(s)) == [card_id]

    first = classify_with(monkeypatch, judgments(e1_000660="DIRECT", e1_005930="DIRECT",
                                                 e1_402340="DIRECT"))
    assert first.judge_fixes["direct_lowered"] == 1
    run_id = save(database, card_id, first)
    run = query(database, "SELECT * FROM classification_runs WHERE id = $1", run_id)[0]
    assert run["is_current"] and run["status"] == "ok"
    assert json.loads(run["usage"])["extract"]["model"]
    assert query(database, "SELECT count(*) AS n FROM classification_events"
                           " WHERE run_id = $1", run_id)[0]["n"] == 3
    labels = {(r["stock_code"], r["path"]): r["label"] for r in query(
        database, "SELECT a.stock_code, a.path, a.label FROM classification_event_applicability a"
        " JOIN classification_events e ON e.id = a.event_id WHERE e.order_index = 1")}
    assert labels == {("005930", "industry"): "DIRECT", ("000660", "industry"): "DIRECT",
                      ("402340", "industry"): "INDIRECT_CONTEXT"}
    assert tagged(database, card_id) == {"005930", "000660"}
    assert in_session(database, lambda s: cards_to_classify(s)) == []

    # 재분류: 새 회차가 현재가 되고 색인도 새 판정으로 바뀐다. 이전 회차는 남는다
    second = classify_with(monkeypatch, judgments(e2_000660="DIRECT"))
    second_id = save(database, card_id, second)
    current = query(database, "SELECT id FROM classification_runs WHERE is_current")
    assert [r["id"] for r in current] == [second_id]
    assert tagged(database, card_id) == {"000660"}
    assert query(database, "SELECT count(*) AS n FROM classification_runs")[0]["n"] == 2


@pytest.mark.parametrize("fetched_at", [datetime(2026, 10, 29, 9, 0, tzinfo=UTC), None])
def test_classified_sources_leaves_out_body_not_observed_by_until(database, monkeypatch, fetched_at):
    """기사는 until 전에 공개됐지만 본문을 그 뒤에 받았거나 받은 시각을 모르면 그때는 알 수 없던 내용이다."""
    card_id = setup(database)
    save(database, card_id, classify_with(monkeypatch, judgments(e1_000660="DIRECT")))
    query(database, "UPDATE news SET body_fetched_at = $1", fetched_at)

    hidden = in_session(database, lambda s: classified_sources(s, "000660", until=UNTIL))
    assert hidden["sources"] == [] and hidden["not_observed"] == 1

    later = datetime(2026, 10, 30, tzinfo=UTC)
    shown = in_session(database, lambda s: classified_sources(s, "000660", until=later))
    if fetched_at is None:  # 받은 시각을 모르면 언제 조회해도 뺀다
        assert shown["sources"] == [] and shown["not_observed"] == 1
    else:
        assert [s["source_card_id"] for s in shown["sources"]] == [card_id]
        assert shown["not_observed"] == 0


def test_failed_and_experiment_runs_keep_the_current_one(database, monkeypatch):
    card_id = setup(database)
    ok_id = save(database, card_id, classify_with(monkeypatch, judgments(e1_005930="DIRECT")))

    failed = classify_with(monkeypatch, {}, judge_error=True)
    failed_id = save(database, card_id, failed)
    row = query(database, "SELECT status, is_current, raw_response, error FROM classification_runs"
                          " WHERE id = $1", failed_id)[0]
    assert row["status"] == "failed" and not row["is_current"]
    assert row["raw_response"] and "429" in row["error"]  # 추출 응답 원문은 남는다

    save(database, card_id, classify_with(monkeypatch, judgments(e2_000660="DIRECT")),
         make_current=False)
    current = query(database, "SELECT id FROM classification_runs WHERE is_current")
    assert [r["id"] for r in current] == [ok_id]
    assert tagged(database, card_id) == {"005930"}
    # retry 는 현재 회차가 있는 자료를 다시 고르지 않는다
    assert in_session(database, lambda s: cards_to_classify(s, retry=True)) == []


def test_classified_sources_for_a_stock(database, monkeypatch):
    card_id = setup(database)
    save(database, card_id, classify_with(monkeypatch, judgments(e1_000660="DIRECT",
                                                                 e2_000660="DIRECT")))

    hynix = in_session(database, lambda s: classified_sources(s, "000660", until=UNTIL))
    assert hynix["unclassified"] == 0 and hynix["failed"] == 0
    (source,) = hynix["sources"]
    assert source["source_card_id"] == card_id and source["card_label"] == "DIRECT"
    assert source["card_type"] == "news" and source["body_status"] == "ok"
    assert [(e["path"], e["label"]) for e in source["events"]] == [
        ("industry", "DIRECT"), ("company", "DIRECT"), ("macro", None)]
    # 근거 문장만으로 뜻이 안 통하는 사건은 문맥 번호까지 넘겨야 생성 쪽이 읽을 수 있다
    assert source["events"][1]["sentence_indices"] == [2]
    assert source["events"][1]["context_indices"] == [1]
    assert hynix["not_observed"] == 0

    # 후보가 아닌 종목에도 거시 사건은 공통 배경으로 붙는다
    lg = in_session(database, lambda s: classified_sources(s, "066570", until=UNTIL))
    assert lg["sources"][0]["card_label"] is None
    assert [e["path"] for e in lg["sources"][0]["events"]] == ["macro"]

    # 기준 시각 전에 공개된 자료만
    before = in_session(database, lambda s: classified_sources(
        s, "000660", until=datetime(2026, 10, 27, tzinfo=UTC)))
    assert before["sources"] == []


def test_checks_block_rule_breaking_rows(database, monkeypatch):
    card_id = setup(database)
    run_id = save(database, card_id, classify_with(monkeypatch, judgments()))
    event_id = query(database, "SELECT id FROM classification_events WHERE run_id = $1"
                               " AND order_index = 2", run_id)[0]["id"]
    with pytest.raises(asyncpg.CheckViolationError):  # 관계 경로는 DIRECT 불가
        query(database, """
            INSERT INTO classification_event_applicability
                (event_id, stock_code, label, path, via_stock_code, relation_type, relation_refs,
                 direct_allowed)
            VALUES ($1, '034730', 'DIRECT', 'relation', '402340', 'ownership', '[{}]', false)
        """, event_id)
    with pytest.raises(asyncpg.CheckViolationError):  # 배열 안의 NULL
        query(database, "INSERT INTO classification_events (run_id, order_index, scope, role, tense,"
                        " sentence_indices) VALUES ($1, 9, 'macro', 'cause', 'past', '{1,NULL}')",
              run_id)
    with pytest.raises(asyncpg.UniqueViolationError):  # 같은 관계를 두 번
        query(database, "INSERT INTO company_relations (from_stock_code, to_external_code,"
                        " relation_type, industry_code, source, basis_version)"
                        " VALUES ('000660', 'nvidia', 'supplier', 'memory', 'x', 'x')")
    with pytest.raises(asyncpg.ForeignKeyViolationError):  # 분류 기록이 있는 자료는 못 지운다
        query(database, "DELETE FROM source_card WHERE id = $1", card_id)

    result = alembic(database, "downgrade", "0026_source_card_disclosures", success=False)
    assert "downgrade 를 멈춘다" in result
