"""러너 끝에서 끝까지. complete()·endpoint()·DB 를 바꿔 끼워 외부 호출 없이 돈다."""

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.collectors import stock_analysis as collector
from app.services.stock_analysis import generate as gen

FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"


def report_for(payload: dict) -> dict:
    """샘플 입력마다 돌려줄 보고서. 원인 케이스는 규칙을 지키고, ±1% 케이스는 일부러
    원인을 대서 FLAT_MOVE_* 가 사유로 잡히게 한다."""
    msg = payload["messages"][0]
    return {
        "ticker": payload["code"], "name": payload["stock"], "date": payload["target_date"],
        "as_of": "15:30", "change_pct": payload["change_pct"], "verdict": "explained",
        "summary": {"move": "m", "main_cause": "c", "counter": None, "unexplained": "u"},
        "factors": [{
            "claim": "c", "detail": "d",
            "stance": "bearish" if payload["change_pct"] < 0 else "bullish",
            "direction_match": True, "size_fit": "sufficient", "unconfirmed": False,
            "sources": [{"channel": msg["channel"], "url": msg["url"],
                         "datetime_kst": msg["datetime_kst"], "quote": msg["text"][:20],
                         "match": msg["match"], "is_market_recap": False}],
        }],
        "terms": [], "background": {"bullish": [], "bearish": [], "neutral": []}, "not_found": [],
    }


@pytest.fixture(autouse=True)
def openrouter(monkeypatch):
    """개인 ai/.env 의 LLM_PROVIDER 가 통화를 바꾸지 않게 고정한다."""
    monkeypatch.setattr(gen.settings, "llm_provider", "openrouter")


@pytest.fixture
def fake_llm(monkeypatch):
    async def fake(system, user):
        return json.dumps(report_for(json.loads(user)), ensure_ascii=False), {"cost": 0.01}

    mock = AsyncMock(side_effect=fake)
    monkeypatch.setattr(gen, "complete", mock)
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    return mock


def only_run_dir(root: Path) -> Path:
    dirs = list(root.iterdir())
    assert len(dirs) == 1
    return dirs[0]


async def test_runs_folder_of_samples_and_writes_wrappers(fake_llm, tmp_path, capsys):
    result = await collector.run(FIXTURES, out_root=tmp_path)

    assert fake_llm.await_count == 2
    assert (result["total"], result["passed"], result["failed"], result["errors"]) == (2, 1, 1, 0)
    assert result["cost"] == pytest.approx(0.02)
    assert result["reasons"] == {"FLAT_MOVE_FACTORS": 1, "FLAT_MOVE_VERDICT": 1}
    assert result["loaded"] is None

    run_dir = only_run_dir(tmp_path)
    wrappers = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in (run_dir / "parsed").glob("*.json")}
    assert set(wrappers) == {"솔마루전자-2026-09-18-1530__r1", "하늬결화학-2026-09-18-1100__r1"}

    cause = wrappers["솔마루전자-2026-09-18-1530__r1"]
    assert cause["verify_status"] == "passed" and cause["verify_problems"] == []
    assert cause["json_status"] == "clean"
    # 입력은 바이트 그대로 복사되고 래퍼가 그 위치와 해시를 가리킨다
    original = (FIXTURES / "sample_cause.json").read_bytes()
    assert (run_dir / cause["input_path"]).read_bytes() == original
    assert cause["input_path"] == "inputs/솔마루전자-2026-09-18-1530__r1.json"
    assert cause["input_sha256"] == hashlib.sha256(original).hexdigest()
    assert cause["input_original_path"].endswith("fixtures/stock_analysis/sample_cause.json")
    assert cause["cost_currency"] == "USD"

    flat = wrappers["하늬결화학-2026-09-18-1100__r1"]
    assert flat["verify_status"] == "failed"

    out = capsys.readouterr().out
    assert ("완료: 보고서 2건 · 검증 통과 1건 · 검증 실패 보고서 1건 (그중 실행 오류 0건)"
            " · $0.0200") in out
    # 실패 보고서는 1건인데 사유는 둘이다. 두 숫자를 섞어 출력하면 안 된다.
    assert "): FLAT_MOVE_FACTORS=1, FLAT_MOVE_VERDICT=1" in out
    assert result["failed"] == 1 and sum(result["reasons"].values()) == 2


async def test_elice_cost_is_reported_in_won(fake_llm, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gen.settings, "llm_provider", "elice")
    result = await collector.run(FIXTURES, out_root=tmp_path)
    assert result["currency"] == "KRW"
    assert "· ₩0.02 ·" in capsys.readouterr().out


async def test_single_file_and_llm_error_does_not_stop_others(monkeypatch, tmp_path, capsys):
    from app.llm.client import LLMError

    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=LLMError("LLM 호출 실패: HTTP 500")))
    result = await collector.run(FIXTURES / "sample_cause.json", out_root=tmp_path)
    assert (result["total"], result["failed"], result["errors"]) == (1, 1, 1)
    assert result["reasons"] == {"LLM_ERROR": 1}
    wrapper = json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json"))
                         .read_text(encoding="utf-8"))
    assert wrapper["is_error"] is True and wrapper["verify_status"] == "failed"


async def test_missing_endpoint_stops_before_any_call_or_directory(monkeypatch, tmp_path):
    complete = AsyncMock()
    monkeypatch.setattr(gen, "complete", complete)
    monkeypatch.setattr(collector, "endpoint",
                        MagicMock(side_effect=RuntimeError("OPENROUTER_API_KEY 가 필요하다")))
    with pytest.raises(RuntimeError):
        await collector.run(FIXTURES, out_root=tmp_path)
    complete.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


async def test_broken_input_stops_before_any_call(fake_llm, tmp_path):
    inputs = tmp_path / "in"
    inputs.mkdir()
    (inputs / "a.json").write_bytes((FIXTURES / "sample_cause.json").read_bytes())
    (inputs / "b.json").write_text('{"stock": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="b.json"):
        await collector.run(inputs, out_root=tmp_path / "runs")
    fake_llm.assert_not_awaited()


async def test_same_case_twice_gets_separate_run_ids(fake_llm, tmp_path):
    inputs = tmp_path / "in"
    inputs.mkdir()
    for name in ("a.json", "b.json"):
        (inputs / name).write_bytes((FIXTURES / "sample_cause.json").read_bytes())
    await collector.run(inputs, out_root=tmp_path / "runs")
    parsed = only_run_dir(tmp_path / "runs") / "parsed"
    assert sorted(p.stem for p in parsed.glob("*.json")) == [
        "솔마루전자-2026-09-18-1530__r1", "솔마루전자-2026-09-18-1530__r2"]


async def test_load_passes_verdicts_and_prompt_version(fake_llm, tmp_path, monkeypatch):
    session = MagicMock(commit=AsyncMock())

    @asynccontextmanager
    async def fake_session():
        yield session

    insert = AsyncMock(return_value=["row1", "row2"])
    monkeypatch.setattr(collector, "SessionLocal", fake_session)
    monkeypatch.setattr(collector, "insert_analysis_files", insert)

    result = await collector.run(FIXTURES, out_root=tmp_path, load=True)
    assert result["loaded"] == 2
    session.commit.assert_awaited_once()
    kwargs = insert.await_args.kwargs
    assert kwargs["prompt_version"] == gen.prompt_sha256()[:12]
    verdicts = kwargs["verdicts"]
    assert verdicts["솔마루전자-2026-09-18-1530__r1"] == ("passed", None)
    status, error = verdicts["하늬결화학-2026-09-18-1100__r1"]
    assert status == "failed" and "FLAT_MOVE_VERDICT" in error
    paths = insert.await_args.args[1]
    assert all(p.exists() and p.parent.name == "parsed" for p in paths)
