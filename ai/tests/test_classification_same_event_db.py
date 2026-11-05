"""같은 사건 묶기의 저장·실행을 실제 PostgreSQL 에서 본다. LLM 은 가짜다.

    - 표가 사건 하나를 묶음 하나에만 넣고, 비용을 들인 기록을 지우지 못하게 막는다
    - 후보가 없으면 부르지 않고 새 묶음을 만든다. 있으면 호출 기록과 함께 저장한다
    - 호출이 실패하거나 응답에 없는 사건은 묶지 않은 채로 두고 다음 실행에서 다시 본다
    - 대상은 현재 회차의 company·industry 사건이고, 공개 시각이 없는 자료는 뺀다
    - 재분류한 사건은 다시 묶고, 옛 소속은 남긴다
    - --dry-run 은 아무것도 남기지 않는다
"""

import json
from datetime import datetime, timedelta

import asyncpg
import pytest

from app.core.config import settings
from app.repositories.classification import classified_sources, save_run, sync_basis
from app.repositories.classification_same_event import cluster_counts
from app.repositories.news import save_news
from app.repositories.source_card import register_missing_sources
from app.services.classification import llm
from app.services.classification.same_event_run import cluster_sources
from tests.db import in_session
from tests.test_classification_repository_db import (
    BASIS,
    BODY,
    PUBLISHED,
    TITLE,
    classify_with,
    judgments,
    save,
    setup,
)
from tests.test_migrations import alembic, query

LATER = PUBLISHED + timedelta(days=30)
MOCK_MODEL = "mock/model"


def saved_events(database: str, monkeypatch) -> tuple[int, int, list[int]]:
    """분류를 저장하고 (카드 id, 회차 id, 사건 id 순서대로) 를 돌려준다."""
    card_id = setup(database)
    run_id = save(database, card_id, classify_with(monkeypatch, judgments()))
    rows = query(database, "SELECT id FROM classification_events WHERE run_id = $1"
                           " ORDER BY order_index", run_id)
    return card_id, run_id, [r["id"] for r in rows]


def prepare(database: str) -> None:
    alembic(database, "upgrade", "head")
    in_session(database, lambda s: sync_basis(s, BASIS))


def add_card(database: str, n: int, *, at: datetime = PUBLISHED, body: str = BODY,
             publisher: str | None = None) -> int:
    url = f"https://news{n}.example.com/a/{n}"
    in_session(database, lambda s: save_news(s, [{
        "url": url, "title": TITLE, "publisher": publisher or f"news{n}.example.com",
        "source": "naver", "published_at": at, "summary": "", "cleaned_text": body,
        "body_status": "ok", "body_error": None, "body_fetched_at": at, "body_extractor": "naver",
    }]))
    in_session(database, register_missing_sources)
    card_id = query(database, "SELECT c.id FROM source_card c JOIN news n ON n.id = c.news_id"
                              " WHERE n.url = $1", url)[0]["id"]
    query(database, "UPDATE source_card SET available_at = $1 WHERE id = $2", at, card_id)
    return card_id


def classified_card(database: str, monkeypatch, n: int, *, at: datetime = PUBLISHED,
                    publisher: str | None = None, **save_kwargs) -> int:
    """기사 하나를 만들어 분류까지 저장한다. 사건 셋: 1 산업(D램), 2 회사(SK하이닉스), 3 거시."""
    card_id = add_card(database, n, at=at, publisher=publisher)
    save(database, card_id, classify_with(monkeypatch, judgments()), **save_kwargs)
    return card_id


def event_ids(database: str, card_id: int) -> dict[int, int]:
    """현재 회차의 사건 순서 → 사건 id."""
    return {r["order_index"]: r["id"] for r in query(
        database, "SELECT e.order_index, e.id FROM classification_events e"
        " JOIN classification_runs r ON r.id = e.run_id"
        " WHERE r.source_card_id = $1 AND r.is_current", card_id)}


def members(database: str) -> dict[int, int]:
    return {r["event_id"]: r["cluster_id"] for r in query(
        database, "SELECT event_id, cluster_id FROM classification_event_cluster_members")}


def fake_same_event(monkeypatch, reply) -> list[str]:
    """묶기 호출을 가짜로 바꾼다. reply 는 (user 문자열) → 응답. 보낸 메시지 목록을 돌려준다."""
    sent: list[str] = []

    async def complete(system, user, **kwargs):
        sent.append(user)
        result = reply(user)
        if isinstance(result, Exception):
            raise result
        return result, {"finish_reason": "stop", "cost": 1.5}

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(settings, "summary_model", MOCK_MODEL)
    monkeypatch.setattr(settings, "classification_same_event_model", None)
    return sent


def assignments(*pairs: tuple[int, int | None]) -> str:
    return json.dumps({"assignments": [{"event": e, "cluster": c} for e, c in pairs]})


def run(database: str, **kwargs):
    return in_session(database, lambda s: cluster_sources(s, report=lambda _: None, **kwargs))


# ── 표 ───────────────────────────────────────────────────────────────────


def test_tables_keep_one_cluster_per_event_and_block_deleting_history(database, monkeypatch):
    card_id, run_id, (first, second, _) = saved_events(database, monkeypatch)
    cluster = query(database, "INSERT INTO classification_event_clusters (representative_event_id)"
                              " VALUES ($1) RETURNING id", first)[0]["id"]
    query(database, "INSERT INTO classification_event_cluster_members (event_id, cluster_id)"
                    " VALUES ($1, $2)", first, cluster)

    with pytest.raises(asyncpg.UniqueViolationError):  # 사건 하나는 묶음 하나에만
        query(database, "INSERT INTO classification_event_cluster_members (event_id, cluster_id)"
                        " VALUES ($1, $2)", first, cluster)
    with pytest.raises(asyncpg.UniqueViolationError):  # 사건 하나가 묶음 둘의 대표가 될 수 없다
        query(database, "INSERT INTO classification_event_clusters (representative_event_id)"
                        " VALUES ($1)", first)
    with pytest.raises(asyncpg.CheckViolationError):
        query(database, "INSERT INTO classification_cluster_calls"
                        " (source_card_id, status, model, prompt_sha256)"
                        " VALUES ($1, 'skipped', 'm', 'x')", card_id)
    with pytest.raises(asyncpg.ForeignKeyViolationError):  # 소속이 있는 회차는 못 지운다
        query(database, "DELETE FROM classification_runs WHERE id = $1", run_id)
    with pytest.raises(asyncpg.ForeignKeyViolationError):  # 없는 호출을 가리킬 수 없다
        query(database, "INSERT INTO classification_event_cluster_members"
                        " (event_id, cluster_id, call_id) VALUES ($1, $2, 999)", second, cluster)


@pytest.mark.parametrize("table", ["classification_event_clusters", "classification_cluster_calls"])
def test_downgrade_stops_when_results_exist(database, monkeypatch, table):
    card_id, _, (first, _, _) = saved_events(database, monkeypatch)
    if table == "classification_event_clusters":
        query(database, "INSERT INTO classification_event_clusters (representative_event_id)"
                        " VALUES ($1)", first)
    else:
        query(database, "INSERT INTO classification_cluster_calls"
                        " (source_card_id, status, model, prompt_sha256)"
                        " VALUES ($1, 'failed', 'm', 'x')", card_id)

    result = alembic(database, "downgrade", "0028_stock_move_analysis_display", success=False)
    assert "downgrade 를 멈춘다" in result and table in result
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] \
        == "0029_classification_same_event"


# ── 실행 ─────────────────────────────────────────────────────────────────


def test_first_source_makes_clusters_without_calling(database, monkeypatch):
    prepare(database)
    card = classified_card(database, monkeypatch, 1)
    sent = fake_same_event(monkeypatch, lambda _: "")
    summary = run(database)

    assert sent == [] and summary.calls == 0 and summary.sources == 1
    ids = event_ids(database, card)
    placed = members(database)
    # 거시 사건은 묶지 않는다
    assert set(placed) == {ids[1], ids[2]}
    assert query(database, "SELECT count(*) AS n FROM classification_cluster_calls")[0]["n"] == 0
    assert query(database, "SELECT count(*) AS n FROM classification_event_cluster_members"
                           " WHERE call_id IS NOT NULL")[0]["n"] == 0
    representatives = {r["id"]: r["representative_event_id"] for r in query(
        database, "SELECT id, representative_event_id FROM classification_event_clusters")}
    assert representatives == {placed[ids[1]]: ids[1], placed[ids[2]]: ids[2]}


def test_second_source_joins_and_leaves_a_call_record(database, monkeypatch):
    prepare(database)
    first = classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)
    placed = members(database)
    first_ids = event_ids(database, first)
    industry, company = placed[first_ids[1]], placed[first_ids[2]]

    second = classified_card(database, monkeypatch, 2, at=PUBLISHED + timedelta(hours=47))
    sent = fake_same_event(monkeypatch, lambda _: assignments((1, industry), (2, None)))
    summary = run(database)

    assert summary.calls == 1 and summary.failures == 0 and summary.cost == pytest.approx(1.5)
    # 묶음마다 scope 가 같은 후보만 간다
    assert f"[묶음 {industry}]" in sent[0] and f"후보 묶음: {company}" in sent[0]
    second_ids = event_ids(database, second)
    placed = members(database)
    assert placed[second_ids[1]] == industry
    assert placed[second_ids[2]] not in {industry, company}  # null 이면 새 묶음

    call = query(database, "SELECT * FROM classification_cluster_calls")[0]
    assert call["source_card_id"] == second and call["status"] == "ok"
    assert call["model"] == MOCK_MODEL and call["raw_response"] and len(call["prompt_sha256"]) == 64
    assert json.loads(call["usage"])["model"] == MOCK_MODEL
    assert json.loads(call["fixes"])["outside_new"] == 0
    call_ids = {r["event_id"]: r["call_id"] for r in query(
        database, "SELECT event_id, call_id FROM classification_event_cluster_members")}
    assert call_ids[second_ids[1]] == call["id"] and call_ids[first_ids[1]] is None


def test_outside_number_makes_new_cluster_and_is_recorded(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)

    second = classified_card(database, monkeypatch, 2)
    fake_same_event(monkeypatch, lambda _: assignments((1, 99999), (2, None)))
    summary = run(database)
    assert summary.fixes["outside_new"] == 1
    assert json.loads(query(database, "SELECT fixes FROM classification_cluster_calls")[0]["fixes"])[
        "outside_new"] == 1
    ids = event_ids(database, second)
    placed = members(database)
    assert ids[1] in placed and ids[2] in placed and ids[3] not in placed


def test_failed_call_leaves_source_and_next_run_retries(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)
    before = dict(members(database))

    second = classified_card(database, monkeypatch, 2)
    fake_same_event(monkeypatch, lambda _: "깨진 응답")
    summary = run(database)
    assert summary.failures == 1 and summary.calls == 1
    assert members(database) == before  # 후보 없는 사건까지 그 자료는 통째로 남는다
    call = query(database, "SELECT status, raw_response, error FROM classification_cluster_calls")[0]
    assert call["status"] == "failed" and call["raw_response"] == "깨진 응답" and "JSON" in call["error"]

    fake_same_event(monkeypatch, lambda _: llm.LLMError("LLM 호출 실패: HTTP 500"))
    assert run(database).failures == 1
    errors = query(database, "SELECT raw_response, error FROM classification_cluster_calls ORDER BY id")
    assert errors[1]["raw_response"] is None and "500" in errors[1]["error"]

    fake_same_event(monkeypatch, lambda _: assignments((1, None), (2, None)))
    assert run(database).failures == 0
    assert set(event_ids(database, second).values()) - set(members(database)) \
        == {event_ids(database, second)[3]}


def test_missing_event_is_seen_again_next_run(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)

    second = classified_card(database, monkeypatch, 2)
    fake_same_event(monkeypatch, lambda _: assignments((1, None)))
    assert run(database).fixes["missing_left"] == 1
    ids = event_ids(database, second)
    assert ids[1] in members(database) and ids[2] not in members(database)

    # 두 번째 실행에는 남은 사건만 간다. 자기 회차가 대표인 묶음은 후보가 아니다
    sent = fake_same_event(monkeypatch, lambda _: assignments((2, None)))
    run(database)
    assert "[사건 2]" in sent[0] and "[사건 1]" not in sent[0]
    placed = members(database)
    own_cluster = placed[ids[1]]
    assert f"[묶음 {own_cluster}]" not in sent[0]
    assert ids[2] in placed


def test_only_current_run_targets_with_time_are_picked(database, monkeypatch):
    prepare(database)
    current = classified_card(database, monkeypatch, 1)
    experiment = classified_card(database, monkeypatch, 2, make_current=False)
    no_time = classified_card(database, monkeypatch, 3)
    query(database, "UPDATE source_card SET available_at = NULL WHERE id = $1", no_time)
    fake_same_event(monkeypatch, lambda _: "")
    summary = run(database)

    assert summary.sources == 1
    assert event_ids(database, experiment) == {}
    scopes = {r["scope"] for r in query(
        database, "SELECT e.scope, r.source_card_id FROM classification_event_cluster_members m"
        " JOIN classification_events e ON e.id = m.event_id"
        " JOIN classification_runs r ON r.id = e.run_id")}
    assert scopes == {"company", "industry"}
    cards = {r["source_card_id"] for r in query(
        database, "SELECT r.source_card_id FROM classification_event_cluster_members m"
        " JOIN classification_events e ON e.id = m.event_id"
        " JOIN classification_runs r ON r.id = e.run_id")}
    assert cards == {current}


def test_earliest_source_first_with_since_and_limit(database, monkeypatch):
    prepare(database)
    later = classified_card(database, monkeypatch, 1, at=PUBLISHED + timedelta(days=9))
    early = classified_card(database, monkeypatch, 2, at=PUBLISHED)
    middle = classified_card(database, monkeypatch, 3, at=PUBLISHED + timedelta(days=5))
    fake_same_event(monkeypatch, lambda _: "")

    run(database, since=PUBLISHED + timedelta(days=1), limit=1)
    ids = set(members(database))
    assert ids == {event_ids(database, middle)[1], event_ids(database, middle)[2]}

    run(database, limit=1)
    assert event_ids(database, early)[1] in members(database)
    assert event_ids(database, later)[1] not in members(database)


def test_outside_48_hours_is_not_sent(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    classified_card(database, monkeypatch, 2, at=PUBLISHED + timedelta(hours=49))
    sent = fake_same_event(monkeypatch, lambda _: "")
    summary = run(database)
    assert sent == [] and summary.calls == 0 and len(summary.clusters) == 4


def test_changed_representative_body_is_dropped_from_candidates(database, monkeypatch):
    prepare(database)
    first = classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)
    query(database, "UPDATE news SET cleaned_text = '고친 본문' WHERE id ="
                    " (SELECT news_id FROM source_card WHERE id = $1)", first)

    classified_card(database, monkeypatch, 2)
    sent = fake_same_event(monkeypatch, lambda _: "")
    summary = run(database)
    assert sent == [] and summary.fixes["representative_unreadable"] == 2


def test_changed_own_body_leaves_source_and_counts_failure(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)
    before = dict(members(database))

    second = classified_card(database, monkeypatch, 2)
    query(database, "UPDATE news SET cleaned_text = '고친 본문' WHERE id ="
                    " (SELECT news_id FROM source_card WHERE id = $1)", second)
    sent = fake_same_event(monkeypatch, lambda _: "")
    summary = run(database)
    assert sent == [] and summary.failures == 1 and summary.calls == 0
    assert members(database) == before
    assert query(database, "SELECT count(*) AS n FROM classification_cluster_calls")[0]["n"] == 0


def test_reclassified_events_are_clustered_again_and_old_membership_stays(database, monkeypatch):
    prepare(database)
    first_card = classified_card(database, monkeypatch, 1)  # 시각이 같으면 id 가 작은 자료가 먼저다
    classified_card(database, monkeypatch, 2)
    fake_same_event(monkeypatch, lambda _: "")
    # 첫 자료가 대표가 되고, 둘째 자료를 그 묶음에 넣는다
    run(database, limit=1)
    cluster_rows = query(database, "SELECT id, representative_event_id"
                                   " FROM classification_event_clusters ORDER BY id")
    fake_same_event(monkeypatch, lambda _: assignments((1, cluster_rows[0]["id"]),
                                                       (2, cluster_rows[1]["id"])))
    run(database)
    assert len(members(database)) == 4
    before = dict(members(database))

    # 대표를 가진 자료를 다시 분류한다
    save(database, first_card, classify_with(monkeypatch, judgments()))

    sent = fake_same_event(monkeypatch, lambda _: assignments((1, cluster_rows[0]["id"]),
                                                              (2, cluster_rows[1]["id"])))
    summary = run(database)
    # 옛 회차 대표를 후보로 보여 줘 원래 묶음으로 돌아간다
    assert summary.calls == 1 and f"[묶음 {cluster_rows[0]['id']}]" in sent[0]
    after = members(database)
    assert {k: after[k] for k in before} == before  # 옛 소속은 지우지 않는다
    new_ids = event_ids(database, first_card)
    assert after[new_ids[1]] == cluster_rows[0]["id"] and after[new_ids[2]] == cluster_rows[1]["id"]
    # 대표는 바뀌지 않는다
    now = query(database, "SELECT id, representative_event_id FROM classification_event_clusters"
                          " ORDER BY id")
    assert [dict(r) for r in now] == [dict(r) for r in cluster_rows]


def test_dry_run_saves_nothing_but_later_sources_see_earlier_clusters(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    classified_card(database, monkeypatch, 2)
    sent = fake_same_event(monkeypatch, lambda _: assignments((1, None), (2, None)))
    summary = run(database, dry_run=True)

    # 앞 자료의 임시 묶음이 다음 자료의 후보가 되어 호출한다
    assert summary.sources == 2 and summary.calls == 1 and len(sent) == 1
    assert summary.cost == pytest.approx(1.5) and len(summary.clusters) == 4
    for table in ("classification_event_clusters", "classification_event_cluster_members",
                  "classification_cluster_calls"):
        assert query(database, f"SELECT count(*) AS n FROM {table}")[0]["n"] == 0


# ── 개수 ─────────────────────────────────────────────────────────────────


def company_cluster(database: str, *cards: int) -> int:
    """자료들의 회사 사건(2번)을 묶음 하나에 넣고 묶음 번호를 돌려준다. 첫 자료가 대표다."""
    first = event_ids(database, cards[0])[2]
    cluster_id = query(database, "INSERT INTO classification_event_clusters"
                                 " (representative_event_id) VALUES ($1) RETURNING id", first)[0]["id"]
    for card in cards:
        query(database, "INSERT INTO classification_event_cluster_members (event_id, cluster_id)"
                        " VALUES ($1, $2)", event_ids(database, card)[2], cluster_id)
    return cluster_id


def counts_of(database: str, cluster_id: int, *, until: datetime = LATER, since=None) -> dict:
    return in_session(database, lambda s: cluster_counts(
        s, {cluster_id}, until=until, since=since))[cluster_id]


def test_counts_sources_publishers_and_types_across_kinds(database, monkeypatch):
    prepare(database)
    news = classified_card(database, monkeypatch, 1, publisher="same.example.com")
    rewritten = classified_card(database, monkeypatch, 2, publisher="same.example.com")
    other = classified_card(database, monkeypatch, 3, publisher="other.example.com")
    query(database, """
        INSERT INTO analyst_reports (source, source_category, source_id, category, title, write_date,
                                     body_status, body_text, body_fetched_at, pdf_sha256, broker)
        VALUES ('naver', 'company', '1', 'company', '리포트', '2026-10-28', 'ok', $1, $2, $3, '하나증권')
    """, BODY, PUBLISHED, "a" * 64)
    query(database, "INSERT INTO channel (telegram_handle, name, is_public, created_at)"
                    " VALUES ('mock_channel', '목업 채널', true, now())")
    query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, posted_at, text, collected_via,
                                       collected_at)
        SELECT id, 1, 'https://t.me/mock_channel/1', $1, $2, 'web', $1 FROM channel
    """, PUBLISHED, BODY)
    in_session(database, register_missing_sources)
    pdf, message = (query(database, "SELECT id FROM source_card WHERE card_type = $1", kind)[0]["id"]
                    for kind in ("pdf", "message"))
    for card in (pdf, message):
        query(database, "UPDATE source_card SET available_at = $1 WHERE id = $2", PUBLISHED, card)
        save(database, card, classify_with(monkeypatch, judgments()))

    cluster = company_cluster(database, news, rewritten, other, pdf, message)
    assert counts_of(database, cluster) == {
        "source_count": 5, "publisher_count": 4,  # 한 매체가 고쳐 올린 기사는 출처를 늘리지 않는다
        "counts_by_type": {"news": 3, "pdf": 1, "message": 1},
    }


def test_two_events_of_one_source_count_once(database, monkeypatch):
    prepare(database)
    card = classified_card(database, monkeypatch, 1)
    cluster = company_cluster(database, card)
    query(database, "INSERT INTO classification_event_cluster_members (event_id, cluster_id)"
                    " VALUES ($1, $2)", event_ids(database, card)[1], cluster)
    assert counts_of(database, cluster)["source_count"] == 1


def message_sharing(database: str, monkeypatch, article: int, *, n: int = 1) -> int:
    """기사를 링크로 공유한 메시지를 만들어 분류까지 저장한다."""
    channel = query(database, "INSERT INTO channel (telegram_handle, name, is_public, created_at)"
                              " VALUES ($1, $2, true, now()) RETURNING id",
                    f"mock_channel_{n}", f"목업 채널 {n}")[0]["id"]
    message = query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, posted_at, text, collected_via,
                                       collected_at)
        VALUES ($1, 1, $2, $3, $4, 'web', $3) RETURNING id
    """, channel, f"https://t.me/mock_channel_{n}/1", PUBLISHED, BODY)[0]["id"]
    query(database, """
        INSERT INTO telegram_message_links (message_id, kind, position, discovered_url, status, news_id)
        SELECT $1, 'url', 0, 'https://news.example.com/shared', 'ok', news_id
        FROM source_card WHERE id = $2
    """, message, article)
    in_session(database, register_missing_sources)
    card = query(database, "SELECT id FROM source_card WHERE telegram_message_id = $1", message)[0]["id"]
    query(database, "UPDATE source_card SET available_at = $1 WHERE id = $2", PUBLISHED, card)
    save(database, card, classify_with(monkeypatch, judgments()))
    return card


def test_message_sharing_a_counted_article_is_left_out(database, monkeypatch):
    prepare(database)
    article = classified_card(database, monkeypatch, 1)
    message = message_sharing(database, monkeypatch, article)
    cluster = company_cluster(database, article, message)
    assert counts_of(database, cluster) == {
        "source_count": 1, "publisher_count": 1, "counts_by_type": {"news": 1},
    }


def test_message_sharing_an_article_outside_the_cluster_is_counted(database, monkeypatch):
    prepare(database)
    inside = classified_card(database, monkeypatch, 1)
    outside = classified_card(database, monkeypatch, 2)
    message = message_sharing(database, monkeypatch, outside)
    cluster = company_cluster(database, inside, message)
    assert counts_of(database, cluster)["counts_by_type"] == {"news": 1, "message": 1}


def test_message_counts_until_the_shared_article_is_seen(database, monkeypatch):
    """기준 시각에 기사를 아직 못 봤으면 그때는 메시지가 유일한 자료다."""
    prepare(database)
    article = classified_card(database, monkeypatch, 1, at=PUBLISHED + timedelta(hours=5))
    message = message_sharing(database, monkeypatch, article)
    cluster = company_cluster(database, article, message)
    early = counts_of(database, cluster, until=PUBLISHED + timedelta(hours=1))
    assert early["counts_by_type"] == {"message": 1}
    assert counts_of(database, cluster)["counts_by_type"] == {"news": 1}


def test_counts_leave_out_sources_after_until_or_before_since(database, monkeypatch):
    prepare(database)
    early = classified_card(database, monkeypatch, 1, at=PUBLISHED)
    late = classified_card(database, monkeypatch, 2, at=PUBLISHED + timedelta(hours=10))
    cluster = company_cluster(database, early, late)

    assert counts_of(database, cluster)["source_count"] == 2
    # 기준 시각 뒤에 나온 자료는 수에 넣지 않는다
    assert counts_of(database, cluster, until=PUBLISHED + timedelta(hours=1))["source_count"] == 1
    assert counts_of(database, cluster, since=PUBLISHED + timedelta(hours=1))["source_count"] == 1


@pytest.mark.parametrize("fetched_at", [PUBLISHED + timedelta(hours=5), None])
def test_counts_leave_out_body_not_observed_by_until(database, monkeypatch, fetched_at):
    """공개는 기준 시각 전이어도 본문을 그 뒤에 받았거나 받은 시각을 모르면 그때는 알 수 없었다."""
    prepare(database)
    seen = classified_card(database, monkeypatch, 1)
    unseen = classified_card(database, monkeypatch, 2)
    cluster = company_cluster(database, seen, unseen)
    query(database, "UPDATE news SET body_fetched_at = $1 WHERE id ="
                    " (SELECT news_id FROM source_card WHERE id = $2)", fetched_at, unseen)
    assert counts_of(database, cluster, until=PUBLISHED + timedelta(hours=1))["source_count"] == 1


def test_counts_only_current_run_after_reclassification(database, monkeypatch):
    prepare(database)
    stays = classified_card(database, monkeypatch, 1)
    reclassified = classified_card(database, monkeypatch, 2)
    cluster = company_cluster(database, stays, reclassified)
    save(database, reclassified, classify_with(monkeypatch, judgments()))
    # 옛 회차의 소속은 남지만 수에는 들지 않는다. 새 회차를 다시 묶으면 돌아온다
    assert counts_of(database, cluster)["source_count"] == 1
    query(database, "INSERT INTO classification_event_cluster_members (event_id, cluster_id)"
                    " VALUES ($1, $2)", event_ids(database, reclassified)[2], cluster)
    assert counts_of(database, cluster)["source_count"] == 2


def test_classified_sources_adds_cluster_and_counts_to_each_event(database, monkeypatch):
    prepare(database)
    first = classified_card(database, monkeypatch, 1)
    second = classified_card(database, monkeypatch, 2, at=PUBLISHED + timedelta(hours=10))
    cluster = company_cluster(database, first, second)
    company_only = judgments(e2_000660="DIRECT")
    save(database, first, classify_with(monkeypatch, company_only))
    query(database, "INSERT INTO classification_event_cluster_members (event_id, cluster_id)"
                    " VALUES ($1, $2)", event_ids(database, first)[2], cluster)

    found = in_session(database, lambda s: classified_sources(s, "000660", until=LATER))
    events = {e["path"]: e for e in next(
        s for s in found["sources"] if s["source_card_id"] == first)["events"]}
    assert events["company"]["cluster_id"] == cluster
    assert events["company"]["source_count"] == 2 and events["company"]["publisher_count"] == 2
    assert events["company"]["counts_by_type"] == {"news": 2}
    # 묶이지 않은 사건은 값이 없다. 공통 배경(거시)도 묶지 않는다
    for path in ("industry", "macro"):
        assert events[path]["cluster_id"] is None and events[path]["source_count"] is None
        assert events[path]["publisher_count"] is None and events[path]["counts_by_type"] is None

    # 기준 시각을 앞당기면 그때 없던 자료가 수에서 빠진다
    earlier = in_session(database, lambda s: classified_sources(
        s, "000660", until=PUBLISHED + timedelta(hours=1)))
    (source,) = earlier["sources"]
    company = next(e for e in source["events"] if e["path"] == "company")
    assert company["cluster_id"] == cluster and company["source_count"] == 1


def test_command_summary_has_counts_and_dry_run_counts_unsaved_clusters(database, monkeypatch):
    prepare(database)
    classified_card(database, monkeypatch, 1)
    classified_card(database, monkeypatch, 2)
    cluster_ids: dict[str, int] = {}

    def reply(user: str) -> str:
        numbers = [int(line.split()[1].rstrip("]")) for line in user.splitlines()
                   if line.startswith("[묶음")]
        cluster_ids["first"] = numbers[0]
        return assignments((1, numbers[0]), (2, numbers[1]))

    fake_same_event(monkeypatch, reply)
    summary = run(database, dry_run=True)
    assert summary.counts[cluster_ids["first"]]["source_count"] == 2
    assert query(database, "SELECT count(*) AS n FROM classification_event_clusters")[0]["n"] == 0

    saved = run(database)
    assert sorted(c["source_count"] for c in saved.counts.values()) == [2, 2]


def test_save_run_is_still_usable_after_clustering(database, monkeypatch):
    """묶기가 기존 분류 흐름을 막지 않는다. 묶인 자료도 다시 분류할 수 있다."""
    prepare(database)
    card = classified_card(database, monkeypatch, 1)
    fake_same_event(monkeypatch, lambda _: "")
    run(database)
    result = classify_with(monkeypatch, judgments())
    run_id = in_session(database, lambda s: save_run(s, card, result))
    assert query(database, "SELECT id FROM classification_runs WHERE is_current")[0]["id"] == run_id
