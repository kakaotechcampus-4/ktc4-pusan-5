"""분류 run 이 카드 하나의 저장 실패로 멈추지 않는다 (DB 없이 __main__ 의 의존성을 바꿔 끼운다).

    - save_run·commit 이 실패하면 롤백하고 그 카드를 failed 회차로 남긴다(단계별 사용량·비용 포함)
    - 다음 카드는 그대로 분류·저장한다
    - failed 회차마저 못 남기면 회차 없이 넘어간다
"""

import argparse
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import app.services.classification.__main__ as main
from app.services.classification.llm import StepCall
from app.services.classification.pipeline import ClassificationResult


class FakeSession:
    def __init__(self, log: list[str]):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.log.append("commit")

    async def rollback(self):
        self.log.append("rollback")


def _ok_result() -> ClassificationResult:
    call = StepCall(step="extract", model="m", prompt_sha256="p", raw_response="{}",
                    usage={"prompt_tokens": 10, "cost": 1.5})
    return ClassificationResult(status="ok", basis_version="v1", calls={"extract": call})


@pytest.fixture
def harness(monkeypatch):
    log: list[str] = []
    saved: list[tuple[int, str, bool, str | None, float]] = []
    state = SimpleNamespace(log=log, saved=saved, fail_saves=[])

    async def fake_save_run(session, card_id, result, *, make_current=True):
        if state.fail_saves and state.fail_saves.pop(0):
            raise ConnectionError("connection was closed in the middle of operation")
        saved.append((card_id, result.status, make_current, result.error, result.cost))
        return 100 + len(saved)

    async def fake_get_sources(session, ids, include_body=False):
        return [SimpleNamespace(title="제목", body="본문", has_body=True, kind="news")]

    async def fake_classify(title, body, basis, *, models=None):
        return _ok_result()

    async def fake_versions(session):
        return {"v1"}

    async def fake_cards(session, **kwargs):
        return [11, 12]

    @asynccontextmanager
    async def fake_locks(session_factory, *names):  # 실행 잠금은 test_classification_concurrency 가 본다
        yield

    monkeypatch.setattr(main, "SessionLocal", lambda: FakeSession(log))
    monkeypatch.setattr(main, "collection_locks", fake_locks)
    monkeypatch.setattr(main, "save_run", fake_save_run)
    monkeypatch.setattr(main, "get_sources", fake_get_sources)
    monkeypatch.setattr(main, "classify", fake_classify)
    monkeypatch.setattr(main, "stored_basis_versions", fake_versions)
    monkeypatch.setattr(main, "cards_to_classify", fake_cards)
    monkeypatch.setattr(main, "endpoint", lambda: ("url", "key"))
    monkeypatch.setattr(main, "load_basis", lambda path: SimpleNamespace(version="v1", stocks={}))
    return state


def _args(**kw) -> argparse.Namespace:
    base = {"basis": None, "since": None, "ids": None, "limit": None, "retry": False,
            "experiment": False, "extract_model": None, "link_model": None, "judge_model": None,
            "concurrency": 1}
    return argparse.Namespace(**{**base, **kw})


async def test_save_failure_records_failed_run_and_continues(harness, capsys):
    harness.fail_saves = [True]  # 카드 11 의 첫 저장만 실패
    await main.run_classify(_args())

    # 카드 11: 롤백 → failed 회차(현재 회차 아님, 비용 그대로). 카드 12: 정상 저장
    assert harness.saved[0][:3] == (11, "failed", False)
    assert harness.saved[0][3].startswith("save_failed: ConnectionError")
    # 쓴 비용이 failed 회차에 그대로 남는다(프로바이더 설정에 따라 계산 방식만 다르다)
    assert harness.saved[0][4] == pytest.approx(_ok_result().cost)
    assert harness.saved[1][:4] == (12, "ok", True, None)
    assert harness.log.count("rollback") == 1
    out = capsys.readouterr().out
    assert "저장 실패 1건" in out and "상태 failed 1, ok 1" in out


async def test_when_even_failed_run_cannot_be_saved_moves_on(harness, capsys):
    harness.fail_saves = [True, True]  # 카드 11 의 저장과 failed 회차 기록이 모두 실패
    await main.run_classify(_args())
    assert [s[:2] for s in harness.saved] == [(12, "ok")]
    out = capsys.readouterr().out
    assert "failed 회차도 남기지 못함" in out and "회차 -" in out


def test_failed_on_save_keeps_calls_and_drops_events():
    result = _ok_result()
    result.events = [object()]
    failed = main.failed_on_save(result, RuntimeError("boom"))
    assert failed.status == "failed" and failed.events == []
    assert failed.calls is result.calls and failed.cost == pytest.approx(result.cost)
    assert failed.error == "save_failed: RuntimeError: boom"


async def test_returns_failed_count_and_prints_it(harness, capsys):
    harness.fail_saves = [True]
    assert await main.run_classify(_args()) == 1
    assert "실패 1건 (그중 저장 실패 1건) — 종료 코드 1" in capsys.readouterr().out


async def test_no_body_and_skipped_are_not_failures(harness, monkeypatch, capsys):
    results = iter([ClassificationResult(status="no_body", basis_version="v1"),
                    ClassificationResult(status="skipped", basis_version="v1")])

    async def fake_classify(title, body, basis, *, models=None):
        return next(results)

    monkeypatch.setattr(main, "classify", fake_classify)
    assert await main.run_classify(_args()) == 0
    out = capsys.readouterr().out
    assert "상태 no_body 1, skipped 1" in out and "실패 0건" in out


@pytest.mark.parametrize("failed, code", [(0, None), (2, 1)])
def test_run_command_exit_code_follows_failed_cards(monkeypatch, failed, code):
    async def fake_run(args):
        return failed

    monkeypatch.setattr(main, "run_classify", fake_run)
    monkeypatch.setattr("sys.argv", ["classification", "run"])
    if code is None:
        main.main()
    else:
        with pytest.raises(SystemExit) as info:
            main.main()
        assert info.value.code == code
