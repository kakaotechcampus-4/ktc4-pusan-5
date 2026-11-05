"""같은 사건 묶기의 코드 쪽 판단. LLM·DB 없이 본다."""

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.llm.client import LLMError, load_prompt
from app.services.classification import __main__ as classification_main
from app.services.classification import llm, same_event_run
from app.services.classification.same_event import (
    PROMPT_NAME,
    ClusterEvent,
    SameEventParseError,
    assign_clusters,
    candidates_for,
    entity_code,
    event_text,
    is_candidate,
    parse_assignments,
    unlinked_mentions,
)
from app.services.classification.same_event_run import run_same_event

AT =datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
BODY = "삼성전자가 공장을 짓는다. 회사는 내년에 가동한다. 투자액은 1조원이다."
MOCK_MODEL = "mock/model"


def sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def make_event(event_id: int = 1, *, run_id: int | None = None, order: int = 1,
               scope: str = "company", at: datetime = AT, codes: tuple[str, ...] = ("stock:005930",),
               mentions: tuple[str, ...] = (), sentences: tuple[int, ...] = (1,),
               context: tuple[int, ...] = (), body: str = BODY) -> ClusterEvent:
    return ClusterEvent(
        event_id=event_id, run_id=event_id if run_id is None else run_id, card_id=event_id,
        order_index=order, scope=scope, available_at=at, codes=frozenset(codes),
        mentions=frozenset(mentions), sentence_indices=sentences, context_indices=context,
        splitter_version="v1", input_sha256=sha(body),
    )


def fake_llm(monkeypatch, reply: str = "", *, error: str | None = None) -> AsyncMock:
    async def complete(system, user, **kwargs):
        if error:
            raise LLMError(error)
        return reply, {"finish_reason": "stop"}

    mock = AsyncMock(side_effect=complete)
    monkeypatch.setattr(llm, "complete", mock)
    monkeypatch.setattr(settings, "summary_model", MOCK_MODEL)
    monkeypatch.setattr(settings, "classification_same_event_model", None)
    return mock


def response(*pairs: tuple[object, object]) -> str:
    return json.dumps({"assignments": [{"event": e, "cluster": c} for e, c in pairs]})


# ── 후보 ──────────────────────────────────────────────────────────────────


def test_same_scope_and_code_within_window_is_candidate():
    assert is_candidate(make_event(1), make_event(2))


def test_different_scope_is_not_candidate():
    assert not is_candidate(make_event(1), make_event(2, scope="industry"))


def test_no_overlap_is_not_candidate():
    assert not is_candidate(make_event(1), make_event(2, codes=("stock:000660",)))


def test_unlinked_mention_overlap_is_candidate():
    event = make_event(1, codes=(), mentions=("요코하마",))
    assert is_candidate(event, make_event(2, codes=(), mentions=("요코하마",)))
    assert not is_candidate(event, make_event(2, codes=(), mentions=("오사카",)))


def test_code_and_unlinked_mention_do_not_match_each_other():
    event = make_event(1, codes=("stock:005930",), mentions=())
    assert not is_candidate(event, make_event(2, codes=(), mentions=("stock:005930",)))


@pytest.mark.parametrize("hours, expected", [(47, True), (48, True), (49, False)])
def test_window_is_48_hours_in_both_directions(hours, expected):
    gap = timedelta(hours=hours)
    assert is_candidate(make_event(1), make_event(2, at=AT + gap)) is expected
    assert is_candidate(make_event(1), make_event(2, at=AT - gap)) is expected


def test_representative_from_same_run_is_not_candidate():
    assert not is_candidate(make_event(1, run_id=7), make_event(2, run_id=7))


def test_old_run_of_same_card_stays_candidate():
    """재분류한 자료가 원래 묶음으로 돌아갈 수 있어야 한다."""
    new = make_event(1, run_id=8)
    old = make_event(2, run_id=7)
    assert is_candidate(new, old)


def test_candidates_are_found_per_event():
    first = make_event(1, order=1, run_id=9, codes=("stock:005930",))
    second = make_event(2, order=2, run_id=9, codes=("stock:000660",))
    third = make_event(3, order=3, run_id=9, codes=("stock:999999",))
    representatives = {10: make_event(4, codes=("stock:005930",)),
                       11: make_event(5, codes=("stock:000660", "stock:005930"))}
    assert candidates_for([first, second, third], representatives) == {1: [10, 11], 2: [11], 3: []}


def test_entity_code_separates_kinds():
    assert entity_code("005930", None, None) == "stock:005930"
    assert entity_code(None, "memory", None) == "industry:memory"
    assert entity_code(None, None, "nvidia") == "external:nvidia"


def test_unlinked_mentions_ignore_case_and_spaces_at_the_ends():
    assert unlinked_mentions([" HBM ", "삼성전자", "CXMT"], ["hbm", "삼성전자"]) == {"cxmt"}


# ── 응답 검사 ─────────────────────────────────────────────────────────────


def test_valid_answers_join_or_make_new():
    result = parse_assignments(response((1, 42), (2, None)), {1: [42], 2: [43]})
    assert result.clusters == {1: 42, 2: None}
    assert not any(result.fixes.values())


def test_cluster_outside_candidates_makes_new_and_is_counted():
    result = parse_assignments(response((1, 99)), {1: [42]})
    assert result.clusters == {1: None} and result.fixes["outside_new"] == 1


def test_candidate_of_another_event_is_outside():
    result = parse_assignments(response((1, 43), (2, 43)), {1: [42], 2: [43]})
    assert result.clusters == {1: None, 2: 43} and result.fixes["outside_new"] == 1


def test_missing_event_is_left_unassigned():
    result = parse_assignments(response((1, 42)), {1: [42], 2: [42]})
    assert result.clusters == {1: 42} and result.fixes["missing_left"] == 1


def test_unknown_event_is_dropped():
    result = parse_assignments(response((1, 42), (9, 42)), {1: [42]})
    assert result.clusters == {1: 42} and result.fixes["unknown_dropped"] == 1


def test_same_answer_twice_keeps_one():
    result = parse_assignments(response((1, 42), (1, 42)), {1: [42]})
    assert result.clusters == {1: 42} and result.fixes["duplicate_dropped"] == 1


@pytest.mark.parametrize("pairs", [
    ((1, 42), (1, 43)),
    ((1, 42), (1, None)),
    ((1, 42), (1, 43), (1, 42)),
])
def test_conflicting_answers_are_left_unassigned(pairs):
    result = parse_assignments(response(*pairs), {1: [42, 43]})
    assert result.clusters == {}
    assert result.fixes["conflict_left"] == 1 and result.fixes["missing_left"] == 0


def test_fenced_json_is_read():
    assert parse_assignments(f"```json\n{response((1, 42))}\n```", {1: [42]}).clusters == {1: 42}


@pytest.mark.parametrize("text", [
    "이건 JSON 이 아니다",
    "[]",
    '{"events": []}',
    '{"assignments": [1]}',
    '{"assignments": [{"event": "1", "cluster": 42}]}',
    '{"assignments": [{"event": true, "cluster": 42}]}',
    '{"assignments": [{"event": 1, "cluster": "42"}]}',
    '{"assignments": [{"event": 1, "cluster": true}]}',
])
def test_broken_response_raises(text):
    with pytest.raises(SameEventParseError):
        parse_assignments(text, {1: [42]})


# ── 문장 복원 ─────────────────────────────────────────────────────────────


def test_event_text_finds_sentences_and_context():
    text = event_text(make_event(sentences=(2,), context=(1,)), BODY)
    assert text.sentences == ("회사는 내년에 가동한다.",)
    assert text.context == ("삼성전자가 공장을 짓는다.",)


@pytest.mark.parametrize("body", [None, "", BODY + " 고친 문장."])
def test_event_text_is_none_when_body_is_gone_or_changed(body):
    assert event_text(make_event(), body) is None


def test_event_text_is_none_when_index_is_out_of_range():
    assert event_text(make_event(sentences=(9,)), BODY) is None


# ── 묶기 실행 (LLM 은 가짜) ───────────────────────────────────────────────


def run(events, representatives, bodies=None):
    bodies = {e.card_id: BODY for e in (*events, *representatives.values())} \
        if bodies is None else bodies
    return asyncio.run(assign_clusters(
        events, candidates_for(events, representatives), representatives, bodies))


def test_prompt_file_exists():
    assert "assignments" in load_prompt(PROMPT_NAME)


def test_no_candidate_makes_new_clusters_without_calling(monkeypatch):
    mock = fake_llm(monkeypatch)
    result = run([make_event(1)], {})
    assert result.clusters == {1: None} and result.call is None and result.error is None
    mock.assert_not_awaited()


def test_only_events_with_candidates_are_sent(monkeypatch):
    mock = fake_llm(monkeypatch, response((1, 10)))
    with_candidate = make_event(1, order=1, run_id=9, context=(2,))
    alone = make_event(2, order=2, run_id=9, codes=("stock:000660",), sentences=(3,))
    result = run([with_candidate, alone], {10: make_event(3, sentences=(2,), context=(1,))})

    assert result.clusters == {1: 10, 2: None} and result.asked == {1}
    assert result.call.model == MOCK_MODEL
    user = mock.await_args.args[1]
    assert "[사건 1]" in user and "[사건 2]" not in user and "투자액" not in user
    # 새 사건과 대표 모두 문맥을 함께 보낸다
    assert "[묶음 10]\n  문맥: 삼성전자가 공장을 짓는다.\n  문장: 회사는 내년에 가동한다." in user
    assert "후보 묶음: 10" in user
    assert mock.await_args.kwargs["model"] == MOCK_MODEL


def test_representatives_are_sent_once(monkeypatch):
    mock = fake_llm(monkeypatch, response((1, 10), (2, None)))
    first = make_event(1, order=1, run_id=9)
    second = make_event(2, order=2, run_id=9)
    run([first, second], {10: make_event(3)})
    assert mock.await_args.args[1].count("[묶음 10]") == 1


@pytest.mark.parametrize("kwargs", [{"error": "LLM 호출 실패: HTTP 500"}, {"reply": "깨진 응답"}])
def test_failed_or_broken_call_leaves_whole_source_unassigned(monkeypatch, kwargs):
    fake_llm(monkeypatch, **kwargs)
    alone = make_event(2, order=2, run_id=9, codes=("stock:000660",))
    result = run([make_event(1, order=1, run_id=9), alone], {10: make_event(3)})
    assert result.clusters == {} and result.error and result.call is not None
    assert result.call.raw_response == kwargs.get("reply")


def test_missing_event_stays_unassigned_while_others_are_kept(monkeypatch):
    fake_llm(monkeypatch, response((1, 10)))
    missing = make_event(2, order=2, run_id=9)
    result = run([make_event(1, order=1, run_id=9), missing], {10: make_event(3)})
    assert result.clusters == {1: 10} and result.fixes["missing_left"] == 1


def test_unreadable_representative_is_dropped_from_candidates(monkeypatch):
    mock = fake_llm(monkeypatch)
    event, representative = make_event(1), make_event(2)
    result = run([event], {10: representative}, {event.card_id: BODY, representative.card_id: None})
    assert result.clusters == {1: None} and result.fixes["representative_unreadable"] == 1
    mock.assert_not_awaited()


def test_other_candidate_is_still_sent_when_one_representative_is_unreadable(monkeypatch):
    mock = fake_llm(monkeypatch, response((1, 11)))
    event, gone, kept = make_event(1), make_event(2), make_event(3)
    result = run([event], {10: gone, 11: kept},
                 {event.card_id: BODY, gone.card_id: None, kept.card_id: BODY})
    assert result.clusters == {1: 11} and result.fixes["representative_unreadable"] == 1
    assert "[묶음 10]" not in mock.await_args.args[1]


def test_unreadable_new_source_is_left_without_calling(monkeypatch):
    mock = fake_llm(monkeypatch)
    event, representative = make_event(1), make_event(2)
    result = run([event], {10: representative}, {event.card_id: None, representative.card_id: BODY})
    assert result.clusters == {} and result.error and result.call is None
    mock.assert_not_awaited()


def test_model_can_be_swapped_without_touching_the_other_steps(monkeypatch):
    # luna 말고 다른 모델(Jev 등)로도 시험할 수 있어야 한다
    mock = fake_llm(monkeypatch, response((1, 10)))
    monkeypatch.setattr(settings, "summary_model", "mock/summary")
    assert llm.model_for(llm.SAME_EVENT_STEP) == "mock/summary"

    monkeypatch.setattr(settings, "classification_same_event_model", "mock/same-event")
    monkeypatch.setattr(settings, "classification_judge_model", None)
    result = run([make_event(1)], {10: make_event(2)})
    assert result.call.model == "mock/same-event"
    assert mock.await_args.kwargs["model"] == "mock/same-event"
    assert llm.model_for("judge") == "mock/summary"


def test_command_stops_before_reading_when_key_is_missing(monkeypatch):
    monkeypatch.setattr(same_event_run, "endpoint",
                        MagicMock(side_effect=RuntimeError("키가 없다")))
    with pytest.raises(SystemExit, match="키가 없다"):
        asyncio.run(run_same_event(None, None, False))


def test_command_is_wired_to_the_arguments(monkeypatch):
    seen = {}

    async def fake_run(since, limit, dry_run):
        seen.update(since=since, limit=limit, dry_run=dry_run)

    monkeypatch.setattr(classification_main, "run_same_event", fake_run)
    monkeypatch.setattr("sys.argv", ["x", "same-event", "--since", "2026-11-01", "--limit", "200",
                                     "--dry-run"])
    classification_main.main()
    assert seen == {"since": date(2026, 11, 1), "limit": 200, "dry_run": True}


def test_existing_steps_still_use_settings(monkeypatch):
    monkeypatch.setattr(settings, "summary_model", "some/model")
    monkeypatch.setattr(settings, "classification_judge_model", None)
    assert llm.model_for("judge") == "some/model"
    assert llm.model_for("judge", "override/model") == "override/model"
