"""run 의 동시 처리와 분류 호출의 429 재시도. DB·LLM 을 부르지 않는다."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.client import LLMError, LLMRateLimited
from app.services.classification import __main__ as cli
from app.services.classification import llm
from app.services.classification.basis import load_basis
from app.services.classification.pipeline import ClassificationResult

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")


def fake_run(monkeypatch, card_ids: list[int], *, failed: tuple[int, ...] = ()) -> SimpleNamespace:
    """DB·LLM 자리를 바꿔 끼우고, 동시에 몇 건이 돌았는지와 무엇이 저장됐는지 모은다."""
    seen = SimpleNamespace(active=0, peak=0, started=[], saved={}, order=[], locks=[])

    @asynccontextmanager
    async def collection_locks(session_factory, *sources):
        seen.locks.append(sources)
        seen.order.append("잠금")
        yield
        seen.order.append("해제")

    async def cards_to_classify(session, **kwargs):
        seen.order.append("선택")
        return card_ids

    async def get_sources(session, ids, include_body):
        return [SimpleNamespace(id=ids[0], kind="news", title="제목", body=f"본문 {ids[0]}",
                                has_body=True)]

    async def classify(title, body, basis, *, models):
        card_id = int(body.split()[1])
        seen.started.append(card_id)
        seen.active += 1
        seen.peak = max(seen.peak, seen.active)
        await asyncio.sleep(0.01)
        seen.active -= 1
        return ClassificationResult(status="failed" if card_id in failed else "ok",
                                    basis_version=basis.version, input_sha256=body)

    async def save_run(session, card_id, result, *, make_current):
        seen.saved[card_id] = result.input_sha256
        seen.order.append("저장")
        return card_id * 10

    monkeypatch.setattr(cli, "load_basis", lambda path: BASIS)
    monkeypatch.setattr(cli, "endpoint", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", MagicMock(return_value=AsyncMock()))
    monkeypatch.setattr(cli, "stored_basis_versions", AsyncMock(return_value={BASIS.version}))
    monkeypatch.setattr(cli, "collection_locks", collection_locks)
    monkeypatch.setattr(cli, "cards_to_classify", cards_to_classify)
    monkeypatch.setattr(cli, "get_sources", get_sources)
    monkeypatch.setattr(cli, "classify", classify)
    monkeypatch.setattr(cli, "save_run", save_run)
    return seen


def run_args(concurrency: int) -> argparse.Namespace:
    return argparse.Namespace(
        basis=None, since=None, ids=None, limit=None, retry=False, experiment=False,
        extract_model=None, link_model=None, judge_model=None, concurrency=concurrency,
    )


async def test_runs_up_to_the_limit_and_keeps_each_result_with_its_card(monkeypatch, capsys):
    card_ids = list(range(1, 8))
    seen = fake_run(monkeypatch, card_ids)
    await cli.run_classify(run_args(3))
    assert seen.peak == 3
    # 다른 자료의 결과가 섞여 저장되면 잘못된 종목이 색인에 들어간다
    assert seen.saved == {card_id: f"본문 {card_id}" for card_id in card_ids}
    assert "ok 7" in capsys.readouterr().out


async def test_concurrency_one_keeps_recent_first_order(monkeypatch):
    seen = fake_run(monkeypatch, [9, 5, 2])
    await cli.run_classify(run_args(1))
    assert seen.peak == 1
    assert seen.started == [9, 5, 2]


async def test_failed_card_does_not_stop_the_others(monkeypatch, capsys):
    seen = fake_run(monkeypatch, [1, 2, 3, 4], failed=(2,))
    await cli.run_classify(run_args(2))
    assert set(seen.saved) == {1, 2, 3, 4}
    out = capsys.readouterr().out
    assert "ok 3" in out and "failed 1" in out


async def test_lock_is_held_from_selection_until_every_card_is_saved(monkeypatch):
    seen = fake_run(monkeypatch, [1, 2])
    await cli.run_classify(run_args(2))
    assert seen.locks == [("classification",)]
    # 고르는 동안만 잠그면 겹친 실행이 아직 회차가 없는 같은 자료를 또 고른다
    assert seen.order == ["잠금", "선택", "저장", "저장", "해제"]


async def test_explicit_ids_do_not_wait_for_the_lock(monkeypatch):
    seen = fake_run(monkeypatch, [1, 2])
    args = run_args(2)
    args.ids = [1, 2]
    await cli.run_classify(args)
    assert seen.locks == []
    assert set(seen.saved) == {1, 2}


def test_concurrency_below_one_is_rejected(monkeypatch):
    monkeypatch.setattr("sys.argv", ["classification", "run", "--concurrency", "0"])
    with pytest.raises(SystemExit):
        cli.main()


@pytest.fixture
def waits(monkeypatch) -> AsyncMock:
    sleep = AsyncMock()
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    return sleep


async def test_rate_limited_call_is_sent_again(monkeypatch, waits, caplog):
    complete = AsyncMock(side_effect=[LLMRateLimited("HTTP 429"), LLMRateLimited("HTTP 429"),
                                      ("응답", {"finish_reason": "stop"})])
    monkeypatch.setattr(llm, "complete", complete)
    result = await llm.call("extract", "classification_events", "본문")
    assert result.ok and result.raw_response == "응답"
    assert complete.await_count == 3
    assert waits.await_count == 2
    # 성공한 재시도는 결과에 남지 않으므로 로그로 세어 본다
    assert [r.getMessage().split(":")[0] for r in caplog.records] == ["429 extract"] * 2


async def test_rate_limit_that_never_clears_becomes_the_step_error(monkeypatch, waits):
    complete = AsyncMock(side_effect=LLMRateLimited("HTTP 429"))
    monkeypatch.setattr(llm, "complete", complete)
    result = await llm.call("judge", "classification_events", "본문")
    assert result.error == "judge: HTTP 429"
    assert complete.await_count == len(llm.RATE_LIMIT_WAITS) + 1


async def test_other_errors_are_not_sent_again(monkeypatch, waits):
    complete = AsyncMock(side_effect=LLMError("HTTP 400"))
    monkeypatch.setattr(llm, "complete", complete)
    result = await llm.call("extract", "classification_events", "본문")
    assert result.error == "extract: HTTP 400"
    assert complete.await_count == 1
    waits.assert_not_awaited()
