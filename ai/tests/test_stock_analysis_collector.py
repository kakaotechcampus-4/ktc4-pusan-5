"""러너 끝에서 끝까지. complete()·endpoint()·DB 를 바꿔 끼워 외부 호출 없이 돈다."""

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.collectors import stock_analysis as collector
from app.services.stock_analysis import generate as gen
from app.services.stock_analysis.verify import code_of

FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"


def report_for(payload: dict) -> dict:
    """샘플 입력마다 돌려줄 보고서. 첫 메시지를 등락 층(change_pct 부호)에 맞춘
    sufficient 원인으로 댄다. 상대 층은 비워 둔다. 원인(cause)·더 내린 날(more_down)·
    크게 오른 날(big_up) 케이스는 규칙을 지키고, 등락률 ±1% 이내인 날은 FLAT_MOVE, 첫 메시지가
    간접인 날은 SIZE_FIT_OVER_CAP, 대형주와 같은 몫이 절반 이상인 날(market_driven·
    market_share_down)은 MOVE_SUFFICIENT_STOCK_ONLY 로 떨어진다. opposite 케이스만 background 없이 counter 를 채워
    COUNTER_WITHOUT_BACKGROUND 와 「그중 counter 있음」 집계를 확인한다."""
    msg = payload["messages"][0]
    market = payload.get("market") or {}
    opposite = market.get("move_case") == "opposite"
    return {
        "ticker": payload["code"], "name": payload["stock"], "date": payload["target_date"],
        "as_of": "15:30", "change_pct": payload["change_pct"], "verdict": "explained",
        "relative_verdict": "no_clear_cause",
        "summary": {"move": "m", "main_cause": "c", "relative": None,
                    "counter": "r" if opposite else None, "unexplained": "u"},
        "factors": [{
            "claim": "c", "detail": "d", "layer": "move",
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
    async def fake(system, user, **_):
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

    # 직접 언급이 0건인 up_no_cause 는 LLM 을 부르지 않고 정형 보고서다(skipped_llm).
    # ±1% 이내 날 나머지 2건은 등락 층 원인을 달아 같은 입력으로 한 번 더 부른다(judge_retry). 다시 불러도 같다
    assert fake_llm.await_count == 10
    assert (result["total"], result["passed"], result["failed"], result["errors"]) == (9, 4, 5, 0)
    assert result["cost"] == pytest.approx(0.10)
    assert result["skipped_llm"] == 1
    assert result["retried"] == {"json_retry": 0, "judge_retry": 2}
    assert result["warning_counts"] == {"issue_trace_warnings": 0, "events_problems": 0, "verify_warnings": 0}
    # 사유는 계열 단위다. 코드별 상세는 래퍼 verify_problems 에 있다
    assert result["reasons"] == {"COUNTER_WITHOUT_BACKGROUND": 3, "FLAT_MOVE": 2,
                                 "MOVE_SUFFICIENT_STOCK_ONLY": 2, "SIZE_FIT_OVER_CAP": 1}
    assert result["loaded"] is None
    assert result["move_cases"] == {"flat": 2, "opposite": 3, "normal": 4, "null": 0}
    assert result["opposite_with_counter"] == 3

    run_dir = only_run_dir(tmp_path)
    wrappers = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in (run_dir / "parsed").glob("*.json")}
    assert set(wrappers) == {"솔마루전자-2026-09-18-1530__r1", "하늬결화학-2026-09-18-1100__r1",
                             "솔마루전자-2026-09-21-1530__r1", "솔마루전자-2026-09-22-1530__r1",
                             "하늬결화학-2026-09-22-1530__r1", "솔마루전자-2026-09-23-1530__r1",
                             "솔마루전자-2026-09-24-1530__r1", "솔마루전자-2026-09-25-1530__r1",
                             "하늬결화학-2026-09-25-1530__r1"}

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
    assert cause["judge_retry"] == {"retried": False}
    assert cause["judge_layers"] == {"move": True, "relative": True}
    retried = sorted(k for k, w in wrappers.items() if w["judge_retry"]["retried"])
    assert len(retried) == 2
    assert {code_of(p) for k in retried for p in wrappers[k]["judge_retry"]["first"]["problems"]} == {
        "FLAT_MOVE_VERDICT", "FLAT_MOVE_FACTORS"}

    flat = wrappers["하늬결화학-2026-09-18-1100__r1"]
    assert flat["verify_status"] == "failed"
    # 덜 내린 날 악재를 등락 층 원인으로 댄 방향은 맞다. 다만 중간값(-3.2%)이 등락 전부라
    # 종목 고유 재료를 sufficient 로 둘 수 없고, counter 를 출처 없이 적어 떨어진다
    market = wrappers["솔마루전자-2026-09-21-1530__r1"]
    assert market["verify_status"] == "failed"
    assert {p.split(":")[0] for p in market["verify_problems"]} == {
        "COUNTER_WITHOUT_BACKGROUND", "MOVE_SUFFICIENT_STOCK_ONLY"}
    # 더 내린 날 고객사 악재(직접)를 등락 층 원인으로 댄 보고서는 통과한다
    assert wrappers["솔마루전자-2026-09-24-1530__r1"]["verify_status"] == "passed"
    assert {w["move_case"] for w in wrappers.values()} == {"normal", "flat", "opposite"}
    assert market["move_case"] == "opposite"
    assert wrappers["솔마루전자-2026-09-22-1530__r1"]["move_case"] == "opposite"
    assert wrappers["하늬결화학-2026-09-22-1530__r1"]["move_case"] == "normal"
    assert wrappers["솔마루전자-2026-09-23-1530__r1"]["move_case"] == "opposite"
    assert wrappers["솔마루전자-2026-09-24-1530__r1"]["move_case"] == "normal"

    out = capsys.readouterr().out
    assert ("완료: 보고서 9건 · 검증 통과 4건 · 검증 실패 보고서 5건 (그중 실행 오류 0건)"
            " · $0.1000") in out
    # 사유는 보고서 기준이다. 두 숫자를 섞어 출력하면 안 된다.
    assert ("): COUNTER_WITHOUT_BACKGROUND=3, FLAT_MOVE=2, MOVE_SUFFICIENT_STOCK_ONLY=2,"
            " SIZE_FIT_OVER_CAP=1") in out
    # 한 보고서가 여러 사유에 들어 사유 합(8)이 실패 보고서 수(5)보다 크다
    assert result["failed"] == 5 and sum(result["reasons"].values()) == 8
    assert "경고 건수 (판정과 별도): issue_trace_warnings=0, events_problems=0, verify_warnings=0" in out
    assert "다시 부른 회차: json_retry=0, judge_retry=2 · LLM 없이 정형 보고서: 1" in out
    assert "경우별 건수: flat=2, opposite=3 (그중 counter 있음 3), normal=4, null=0" in out
    # 샘플 보고서에는 events 칸이 없다(정형 보고서만 빈 events). 판정과 따로 missing 으로 센다
    assert result["events"] == {"passed": 1, "failed": 0, "missing": 8}
    assert cause["events_status"] == "missing" and cause["events_problems"] == []
    assert "events 검사 (판정과 별도): passed=1, failed=0, missing=8" in out


async def test_broken_events_are_recorded_apart_from_verify_status(monkeypatch, tmp_path):
    """events 형식이 틀려도 verify_status 는 passed 다. 문제는 events_problems 에만 남는다."""
    async def fake(system, user, **_):
        report = report_for(json.loads(user))
        report["events"] = [{"event": "e", "dup_channels": 1, "placed": "dropped"}]
        return json.dumps(report, ensure_ascii=False), {"cost": 0.01}

    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=fake))
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    result = await collector.run(FIXTURES / "sample_cause.json", out_root=tmp_path)
    assert (result["passed"], result["failed"]) == (1, 0)
    assert result["events"] == {"passed": 0, "failed": 1, "missing": 0}
    wrapper = json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json"))
                         .read_text(encoding="utf-8"))
    assert wrapper["verify_status"] == "passed" and wrapper["verify_problems"] == []
    assert wrapper["events_status"] == "failed"
    # factor 하나를 가리키는 사건이 없어 칸 대조(EVENT_FACTOR_COUNT)도 걸린다
    assert [p.split(":")[0] for p in wrapper["events_problems"]] == ["EVENT_REASON_MISMATCH", "EVENT_FACTOR_COUNT"]


async def test_elice_cost_is_reported_in_won(fake_llm, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gen.settings, "llm_provider", "elice")
    result = await collector.run(FIXTURES, out_root=tmp_path)
    assert result["currency"] == "KRW"
    assert "· ₩0.10 ·" in capsys.readouterr().out


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
    assert wrapper["events_status"] == "missing"


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


async def test_bearish_relative_factor_on_opposite_day_fails(monkeypatch, tmp_path):
    """덜 내린 날 악재를 상대 층(위쪽) 원인으로 대면 DIRECTION_MATCH_WRONG.
    같은 악재를 등락 층에 두면 방향은 맞는다(report_for 그대로)."""
    async def fake(system, user, **_):
        report = report_for(json.loads(user))
        report["factors"][0]["layer"] = "relative"
        report["verdict"], report["relative_verdict"] = "no_clear_cause", "explained"
        report["summary"]["counter"] = None
        return json.dumps(report, ensure_ascii=False), {"cost": 0.01}

    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=fake))
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    result = await collector.run(FIXTURES / "sample_market_driven.json", out_root=tmp_path)

    assert result["reasons"] == {"DIRECTION_MATCH_WRONG": 1}
    wrapper = json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json"))
                         .read_text(encoding="utf-8"))
    assert {p.split(":")[0] for p in wrapper["verify_problems"]} == {"DIRECTION_MATCH_WRONG"}


def _fixed_report(factors, verdict, relative_verdict, relative=None):
    async def fake(system, user, **_):
        report = report_for(json.loads(user))
        report.update(factors=factors, verdict=verdict, relative_verdict=relative_verdict)
        report["summary"].update(relative=relative, counter=None)
        return json.dumps(report, ensure_ascii=False), {"cost": 0.01}
    return fake


def _factor(payload, k, layer, size_fit):
    report = report_for(payload)
    msg = payload["messages"][k]
    f = report["factors"][0]
    f["sources"][0].update(channel=msg["channel"], url=msg["url"], datetime_kst=msg["datetime_kst"],
                           quote=msg["text"][:20], match=msg["match"])
    return {**f, "layer": layer, "size_fit": size_fit}


async def test_same_event_in_both_layers_passes_on_big_up_day(monkeypatch, tmp_path):
    """+6.5%, 중간값 -0.6%. 같은 공급 계약 호재가 move·relative 두 factor 로 들어간다."""
    path = FIXTURES / "sample_big_up.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    factors = [_factor(payload, 0, "move", "sufficient"), _factor(payload, 0, "relative", "sufficient")]
    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=_fixed_report(
        factors, "explained", "explained", "같은 소식으로 다른 대형주보다도 크게 올랐습니다.")))
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    result = await collector.run(path, out_root=tmp_path)
    assert (result["passed"], result["failed"]) == (1, 0)


@pytest.mark.parametrize("size_fit, verdict, reasons", [
    ("sufficient", "explained", {"MOVE_SUFFICIENT_STOCK_ONLY": 1}),
    ("partial", "partially_explained", {}),
])
async def test_stock_only_material_is_capped_on_market_share_day(monkeypatch, tmp_path, size_fit,
                                                                 verdict, reasons):
    """-3.57% 중 -2.62% 가 대형주와 같은 몫. 공장 보수(직접) 하나로는 partial 까지다."""
    path = FIXTURES / "sample_market_share_down.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=_fixed_report(
        [_factor(payload, 0, "move", size_fit)], verdict, "no_clear_cause")))
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    result = await collector.run(path, out_root=tmp_path)
    assert result["reasons"] == reasons


async def test_dropped_move_factor_without_rewrite_warns_main_cause_stale(monkeypatch, tmp_path):
    """quote 고쳐 쓰기와 main_cause 다시 쓰기가 둘 다 실패하면 factor 는 빠지고 MAIN_CAUSE_STALE 경고가
    붙는다. issue_trace 숫자(오른 메시지 / 입력 메시지)도 래퍼와 집계에 남는다."""
    from app.llm.client import LLMError
    from app.services.stock_analysis import repair

    path = FIXTURES / "sample_big_up.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    good = _factor(payload, 0, "move", "sufficient")
    bad = {**good, "claim": "없는 사건",
           "sources": [{**good["sources"][0], "quote": "원문에 없는 문장"}]}

    async def fake(system, user, **_):
        report = report_for(json.loads(user))
        report["factors"] = [bad, good]
        report["issue_trace"] = [{"url": payload["messages"][0]["url"],
                                  "issues": [{"id": "i1", "issue": "x", "relation": "market"}]}]
        return json.dumps(report, ensure_ascii=False), {"cost": 0.01}

    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=fake))
    monkeypatch.setattr(repair, "complete", AsyncMock(side_effect=LLMError("HTTP 500")))
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    result = await collector.run(path, out_root=tmp_path)

    wrapper = json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json"))
                         .read_text(encoding="utf-8"))
    assert wrapper["main_cause_rewrite"]["result"] == "failed"
    assert [w.split(":")[0] for w in wrapper["verify_warnings"]] == ["MAIN_CAUSE_STALE"]
    total = len(payload["messages"])
    assert wrapper["issue_trace_stats"]["messages_traced"] == 1
    assert wrapper["issue_trace_stats"]["market_unreferenced"] == 1
    assert [w.split(":")[0] for w in wrapper["issue_trace_warnings"]] == ["ISSUE_TRACE_MISSING_URL"] * (total - 1)
    assert result["issue_trace_messages"] == {"traced": 1, "total": total}
