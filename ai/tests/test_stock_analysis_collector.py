"""러너 끝에서 끝까지. complete()·endpoint()·DB·KRX 를 바꿔 끼워 외부 호출 없이 돈다."""

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.collectors import stock_analysis as collector
from app.services.market_data import build_market_context
from app.services.market_data import krx as krx_client
from app.services.market_data.errors import KrxError
from app.services.stock_analysis import generate as gen
from app.services.stock_analysis import market_compare as mc
from app.services.stock_analysis import repair as collector_repair
from app.services.stock_analysis.verify import code_of, move_case
from tests.test_market_data_context import DAY, KOSPI, STOCKS

FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"
MARKET_FIXTURES = Path(__file__).parent / "fixtures" / "market_data"
# 2026-10-27 실제 KRX 응답 행. 경로마다 _post 가 돌려주는 값이다
KRX_ROWS = {
    krx_client.KOSPI_INDEX_PATH: "krx_kospi_dd_trd.json",
    krx_client.KOSPI_STOCK_PATH: "krx_stk_bydd_trd.json",
}


def report_for(payload: dict) -> dict:
    """샘플 입력마다 돌려줄 보고서. 첫 메시지를 등락 층(change_pct 부호)에 맞춘
    sufficient 원인으로 댄다. 상대 층은 비워 둔다. 원인(cause)·더 내린 날(more_down)·
    크게 오른 날(big_up) 케이스는 규칙을 지키고, 등락률 ±1% 이내인 날은 FLAT_MOVE, 첫 메시지가
    간접인 날은 SIZE_FIT_OVER_CAP, 대형주와 같은 몫이 절반 이상인 날(market_driven·
    market_share_down)은 MOVE_SUFFICIENT_STOCK_ONLY 로 떨어진다. opposite 케이스만 background 없이 counter 를 채워
    COUNTER_WITHOUT_BACKGROUND 와 「그중 counter 있음」 집계를 확인한다."""
    msg = payload["messages"][0]
    # 모델 입력에는 move_case 가 없다(래퍼 집계에만). 같은 함수로 다시 계산한다
    opposite = move_case(payload) == "opposite"
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


@pytest.fixture(autouse=True)
def krx(monkeypatch):
    """KRX 요청(krx._post) 하나가 호출 하나다. 바꿔 끼워 밖으로 나가지 않고 호출 수를 센다.
    기본은 어느 경로든 빈 응답 — 기준일 데이터가 없는 날(no_data)이다. side_effect 를 바꿔 다른 날을 만든다."""
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(krx_client, "_post", mock)
    return mock


async def real_rows(client, path, bas_dd):
    """2026-10-27 실제 응답. 그 밖의 날은 빈 응답."""
    if bas_dd != DAY:
        return []
    return json.loads((MARKET_FIXTURES / KRX_ROWS[path]).read_text(encoding="utf-8"))["OutBlock_1"]


def same_day_inputs(root: Path, codes: tuple[str, ...]) -> Path:
    """sample_cause 의 종목·기준일만 바꿔 2026-10-27 입력 여러 개를 만든다."""
    base = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
    folder = root / "same_day"
    folder.mkdir()
    for code in codes:
        payload = {**base, "code": code, "stock": f"종목{code}", "target_date": DAY.isoformat()}
        (folder / f"{code}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


def fixture_days() -> int:
    """샘플 입력의 서로 다른 기준일 수."""
    return len({json.loads(p.read_text(encoding="utf-8"))["target_date"] for p in FIXTURES.glob("*.json")})


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
    # 대형주 몫 상한(move_strength_cap)을 어긴 market_driven·market_share_down 도 한 번 더 부른다
    assert fake_llm.await_count == 12
    # 대형주 몫 상한·간접 출처로 sufficient 를 단 보고서는 러너가 strength·판정을 다시 정해(finalize) 그 실패가 없다
    assert (result["total"], result["passed"], result["failed"], result["errors"]) == (9, 5, 4, 0)
    assert result["cost"] == pytest.approx(0.12)
    assert result["skipped_llm"] == 1
    assert result["retried"] == {"json_retry": 0, "judge_retry": 4}
    # market_share_down(-3.57, 대형주 -2.62)은 common_move 날인데 등락 층 원인을 달아 경고 1건,
    # opposite(09-23)는 간접 출처만으로 sufficient 라 STRENGTH_MISMATCH 1건. 경고는 고치기 전 모델 값으로 센다
    assert result["warning_counts"] == {"issue_trace_warnings": 0, "events_problems": 0, "verify_warnings": 2}
    # 사유는 계열 단위다. 코드별 상세는 래퍼 verify_problems 에 있다
    assert result["reasons"] == {"COUNTER_WITHOUT_BACKGROUND": 3, "FLAT_MOVE": 2}
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
    assert [w.split(":")[0] for w in wrappers["하늬결화학-2026-09-25-1530__r1"]["verify_warnings"]] == [
        "COMMON_MOVE_WITH_MOVE_LINK"]
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
    assert len(retried) == 4
    assert {code_of(p) for k in retried for p in wrappers[k]["judge_retry"]["first"]["problems"]} == {
        "FLAT_MOVE_VERDICT", "FLAT_MOVE_FACTORS", "MOVE_SUFFICIENT_STOCK_ONLY"}
    assert wrappers["하늬결화학-2026-09-25-1530__r1"]["move_strength_cap"] == "partial"
    assert cause["move_strength_cap"] is None
    # 샘플 보고서에는 events·issue_trace 가 없어 출처로 본다
    assert cause["strength_recomputed"] == [{"factor": 0, "layer": "move", "model": "sufficient", "final": "sufficient",
                                             "basis": "sources"}]
    assert cause["main_cause_fixed"] is None
    common = wrappers["하늬결화학-2026-09-25-1530__r1"]
    assert common["strength_recomputed"][0]["final"] == "partial"
    assert common["verdict_recomputed"][0] == {"key": "verdict", "model": "explained", "final": "partially_explained"}
    assert json.loads(common["final_text"])["summary"]["main_cause"] == (
        "대형주 전반이 함께 내린 날이었습니다. c 이 종목만의 원인은 따로 확인되지 않았습니다.")
    # 정형 보고서는 러너가 이미 정했다
    assert "strength_recomputed" not in wrappers["하늬결화학-2026-09-22-1530__r1"]

    flat = wrappers["하늬결화학-2026-09-18-1100__r1"]
    assert flat["verify_status"] == "failed"
    # 덜 내린 날 악재를 등락 층 원인으로 댄 방향은 맞다. 중간값(-3.2%)이 등락 전부라 러너가 종목 고유 재료를
    # partial 로 낮추고, counter 를 출처 없이 적어 떨어진다
    market = wrappers["솔마루전자-2026-09-21-1530__r1"]
    assert market["verify_status"] == "failed"
    assert {p.split(":")[0] for p in market["verify_problems"]} == {"COUNTER_WITHOUT_BACKGROUND"}
    # 더 내린 날 고객사 악재(직접)를 등락 층 원인으로 댄 보고서는 통과한다
    assert wrappers["솔마루전자-2026-09-24-1530__r1"]["verify_status"] == "passed"
    assert {w["move_case"] for w in wrappers.values()} == {"normal", "flat", "opposite"}
    assert market["move_case"] == "opposite"
    assert wrappers["솔마루전자-2026-09-22-1530__r1"]["move_case"] == "opposite"
    assert wrappers["하늬결화학-2026-09-22-1530__r1"]["move_case"] == "normal"
    assert wrappers["솔마루전자-2026-09-23-1530__r1"]["move_case"] == "opposite"
    assert wrappers["솔마루전자-2026-09-24-1530__r1"]["move_case"] == "normal"

    out = capsys.readouterr().out
    assert ("완료: 보고서 9건 · 검증 통과 5건 · 검증 실패 보고서 4건 (그중 실행 오류 0건)"
            " · $0.1200") in out
    # 사유는 보고서 기준이다. 두 숫자를 섞어 출력하면 안 된다.
    assert "): COUNTER_WITHOUT_BACKGROUND=3, FLAT_MOVE=2" in out
    # 한 보고서가 여러 사유에 들어 사유 합(5)이 실패 보고서 수(4)보다 크다
    assert result["failed"] == 4 and sum(result["reasons"].values()) == 5
    assert "경고 건수 (판정과 별도): issue_trace_warnings=0, events_problems=0, verify_warnings=2" in out
    assert "다시 부른 회차: json_retry=0, judge_retry=4 · LLM 없이 정형 보고서: 1" in out
    assert "경우별 건수: flat=2, opposite=3 (그중 counter 있음 3), normal=4, null=0" in out
    # 샘플 보고서에는 events 칸이 없다(정형 보고서만 빈 events). 판정과 따로 missing 으로 센다
    assert result["events"] == {"passed": 1, "failed": 0, "missing": 8}
    assert cause["events_status"] == "missing" and cause["events_problems"] == []
    assert "events 검사 (판정과 별도): passed=1, failed=0, missing=8" in out
    assert result["market_compare"] == {"no_data": 9}
    assert "시장 맥락 (failed 는 비교 문장 없이 만듦): no_data=9" in out


async def test_market_compare_goes_into_model_input_and_wrapper(fake_llm, krx, tmp_path):
    """입력 code·target_date 로 시장 맥락을 계산해 모델 입력 market_compare 칸에 넣고 래퍼에 남긴다."""
    krx.side_effect = real_rows
    folder = same_day_inputs(tmp_path, ("105560",))
    runs = tmp_path / "runs"

    result = await collector.run(folder, out_root=runs)

    assert [c.args[1:] for c in krx.await_args_list] == [
        (krx_client.KOSPI_INDEX_PATH, DAY), (krx_client.KOSPI_STOCK_PATH, DAY)]
    expected = mc.to_input(build_market_context("105560", DAY, KOSPI, STOCKS))
    sent = json.loads(fake_llm.await_args_list[0].args[1])
    assert sent["market_compare"] == expected
    assert sent["market_compare"]["kospi"]["kospi_relation"] == "diverges"
    [wrapper] = [json.loads(p.read_text(encoding="utf-8")) for p in (only_run_dir(runs) / "parsed").glob("*.json")]
    assert wrapper["market_compare"] == expected
    assert wrapper["market_compare_error"] is None
    # 입력 사본은 받은 바이트 그대로다. 계산한 칸은 래퍼에만 있다
    assert (only_run_dir(runs) / wrapper["input_path"]).read_bytes() == (folder / "105560.json").read_bytes()
    assert result["market_compare"] == {"ok": 1}


async def test_same_day_reports_call_krx_once_per_day(fake_llm, krx, tmp_path):
    """같은 기준일 3종목 → KRX 호출 2번(코스피 지수·유가증권 전 종목 한 번씩). 계산은 종목마다 따로다."""
    krx.side_effect = real_rows
    runs = tmp_path / "runs"

    result = await collector.run(same_day_inputs(tmp_path, ("005930", "105560", "000660")), out_root=runs)

    assert krx.await_count == 2
    assert sorted(c.args[1] for c in krx.await_args_list) == sorted(KRX_ROWS)
    assert result["market_compare"] == {"ok": 3}
    basis = {w["input_original_path"].rsplit("/", 1)[1]: w["market_compare"]["kospi"]["kospi_basis"]
             for w in (json.loads(p.read_text(encoding="utf-8")) for p in (only_run_dir(runs) / "parsed").glob("*.json"))}
    assert basis == {"005930.json": "kospi_ex_self", "105560.json": "kospi", "000660.json": "kospi_ex_self"}


async def test_each_day_is_asked_once_even_without_data(fake_llm, krx, tmp_path):
    """샘플 9건은 기준일이 fixture_days() 개다. 데이터가 없는 날은 코스피만 묻고 전 종목은 묻지 않는다."""
    await collector.run(FIXTURES, out_root=tmp_path)

    assert krx.await_count == fixture_days() < 9
    assert {c.args[1] for c in krx.await_args_list} == {krx_client.KOSPI_INDEX_PATH}


async def test_krx_failure_still_makes_every_report(fake_llm, krx, tmp_path, capsys):
    """KRX 가 실패해도 멈추지 않는다. 칸이 null 로 가 비교 문장만 빠지고, 판정은 KRX 가 없는 날과 같다."""
    krx.side_effect = KrxError("KRX kospi_dd_trd 20260918 요청 실패: ConnectTimeout: ")

    result = await collector.run(FIXTURES, out_root=tmp_path)

    # 실패도 기준일마다 한 번만 시도한다
    assert krx.await_count == fixture_days()
    assert (result["total"], result["passed"], result["failed"], result["errors"]) == (9, 5, 4, 0)
    assert result["market_compare"] == {"failed": 9}
    assert all(json.loads(c.args[1])["market_compare"] is None for c in fake_llm.await_args_list)
    wrappers = [json.loads(p.read_text(encoding="utf-8"))
                for p in (only_run_dir(tmp_path) / "parsed").glob("*.json")]
    assert all(w["market_compare"] is None for w in wrappers)
    assert all(w["market_compare_error"].startswith("KrxError: KRX kospi_dd_trd") for w in wrappers)
    assert "시장 맥락 (failed 는 비교 문장 없이 만듦): failed=9" in capsys.readouterr().out


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
    assert "· ₩0.12 ·" in capsys.readouterr().out


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


@pytest.mark.parametrize("field, value", [
    ("target_date", "2026/09/18"),
    ("target_date", "../2026-09-18"),
    ("target_date", "2026-13-01"),
    ("cutoff", "2026-09-18T15:30:00"),  # 시간대 없음
    ("cutoff", "15:30"),
    ("cutoff", "2026-09-18"),
])
async def test_bad_date_or_cutoff_stops_before_llm(fake_llm, tmp_path, field, value):
    inputs = tmp_path / "in"
    inputs.mkdir()
    payload = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
    (inputs / "a.json").write_text(json.dumps({**payload, field: value}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        await collector.run(inputs, out_root=tmp_path / "runs")
    fake_llm.assert_not_awaited()
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("n_factors, n_background", [(5, 0), (1, 7)])
async def test_over_cap_report_skips_repair_and_warns(monkeypatch, tmp_path, n_factors, n_background):
    """factor 5개 또는 background 7개. quote 가 틀린 항목이 있어도 고쳐 쓰지 않고 경고와 repair_limit 을 남긴다."""
    path = FIXTURES / "sample_cause.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    bad = _factor(payload, 0, "move", "sufficient")
    bad["sources"][0]["quote"] = "원문에 없는 문장"

    async def fake(system, user, **_):
        r = report_for(json.loads(user))
        r["factors"] = [bad] * n_factors
        r["background"]["bearish"] = [{"text": "t", "sources": bad["sources"]}] * n_background
        return json.dumps(r, ensure_ascii=False), {"cost": 0.01}

    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=fake))
    repair_llm = AsyncMock()
    monkeypatch.setattr(collector_repair, "complete", repair_llm)
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    await collector.run(path, out_root=tmp_path)
    repair_llm.assert_not_awaited()
    wrapper = json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json")).read_text(encoding="utf-8"))
    assert wrapper["repair_limit"] == {"hit": True, "factors": n_factors, "background": n_background, "max_items": 10}
    assert "quote_repair" not in wrapper
    assert [w for w in wrapper["verify_warnings"] if w.startswith("REPAIR_SKIPPED_OVER_CAP")]
    assert wrapper["verify_status"] == "failed"  # 틀린 quote 가 남아 QUOTE_NOT_IN_SOURCE


async def test_run_dir_has_unique_suffix(fake_llm, tmp_path):
    await collector.run(FIXTURES / "sample_cause.json", out_root=tmp_path)
    await collector.run(FIXTURES / "sample_cause.json", out_root=tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 2 and all(len(n.split("-")) == 3 and len(n.split("-")[2]) == 8 for n in names)


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


@pytest.mark.parametrize("size_fit, verdict", [
    ("sufficient", "explained"),
    ("partial", "partially_explained"),
])
async def test_stock_only_material_is_capped_on_market_share_day(monkeypatch, tmp_path, size_fit, verdict):
    """-3.57% 중 -2.62% 가 대형주와 같은 몫. 공장 보수(직접) 하나로는 partial 까지다. 모델이 sufficient 로 적어도
    러너가 partial·partially_explained 로 고친다(finalize). 경고 STRENGTH_MISMATCH 는 상한 예외라 없다."""
    path = FIXTURES / "sample_market_share_down.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=_fixed_report(
        [_factor(payload, 0, "move", size_fit)], verdict, "no_clear_cause")))
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    result = await collector.run(path, out_root=tmp_path)
    assert result["reasons"] == {}
    wrapper = json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json")).read_text(encoding="utf-8"))
    assert wrapper["strength_recomputed"] == [{"factor": 0, "layer": "move", "model": size_fit, "final": "partial",
                                               "basis": "sources"}]
    assert wrapper["verdict_recomputed"][0] == {"key": "verdict", "model": verdict, "final": "partially_explained"}


def _linked(payload, k, event, layers, quote=None):
    """links 형식 factor. 출처는 messages[k], quote 를 주면 그 문장(원문에 없게 만들 때)."""
    f = _factor(payload, k, "move", "sufficient")
    src = {**f["sources"][0], **({"quote": quote} if quote else {})}
    return {"event": event, "detail": "", "stance": f["stance"], "unconfirmed": False, "sources": [src],
            "links": [{"layer": layer, "note": "n", "direction_match": True, "strength": "partial"} for layer in layers]}


async def _run_with_dropped_factor(monkeypatch, tmp_path, factors, summary, repair_replies):
    """+6.5%(중간값 -0.6%) 날. factors[0] 의 quote 가 원문에 없고 고쳐 써도 없어 빠진다. repair 쪽 LLM 응답은
    repair_replies 순서다(첫 번째는 quote 고쳐 쓰기). 래퍼를 돌려준다."""
    from app.services.stock_analysis import repair

    path = FIXTURES / "sample_big_up.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    async def fake(system, user, **_):
        report = report_for(json.loads(user))
        report.update(factors=factors(payload), relative_verdict="partially_explained")
        report["summary"].update(summary)
        return json.dumps(report, ensure_ascii=False), {"cost": 0.01}

    monkeypatch.setattr(gen, "complete", AsyncMock(side_effect=fake))
    repair_llm = AsyncMock(side_effect=repair_replies)
    monkeypatch.setattr(repair, "complete", repair_llm)
    monkeypatch.setattr(collector, "endpoint", MagicMock(return_value=("url", "key")))
    await collector.run(path, out_root=tmp_path)
    assert repair_llm.await_count == len(repair_replies)
    return json.loads(next((only_run_dir(tmp_path) / "parsed").glob("*.json")).read_text(encoding="utf-8"))


# quote 고쳐 쓰기 응답. 같은 사건·같은 url 인데 quote 가 여전히 원문에 없어 factor 가 빠진다.
_BIG_UP_URL = json.loads((FIXTURES / "sample_big_up.json").read_text(encoding="utf-8"))["messages"][0]["url"]
_STILL_BAD = (json.dumps({"event": "없는 사건", "sources": [{"url": _BIG_UP_URL, "quote": "여전히 없는 문장"}]}),
              {"cost": 0.01})


def _relative_factors(payload):
    # 빠지는 factor 는 상대 층만, 남는 factor 는 두 층에 답한다
    return [_linked(payload, 0, "없는 사건", ["relative"], quote="원문에 없는 문장"),
            _linked(payload, 0, "공급 계약", ["move", "relative"])]


async def test_dropped_relative_factor_rewrites_relative_through_collector(monkeypatch, tmp_path):
    wrapper = await _run_with_dropped_factor(
        monkeypatch, tmp_path, _relative_factors, {"relative": "없는 사건과 공급 계약으로 더 올랐습니다."},
        [_STILL_BAD, (json.dumps({"relative": "공급 계약으로 다른 대형주보다 더 올랐습니다."}), {"cost": 0.01})])
    rewrite = wrapper["relative_rewrite"]
    assert (rewrite["result"], rewrite["dropped"]) == ("rewritten", ["없는 사건"])
    assert json.loads(wrapper["final_text"])["summary"]["relative"] == "공급 계약으로 다른 대형주보다 더 올랐습니다."
    assert "main_cause_rewrite" not in wrapper  # 빠진 factor 에 등락 층 link 가 없었다
    assert not [w for w in wrapper["verify_warnings"] if w.startswith("RELATIVE_STALE")]
    assert wrapper["cost"] == pytest.approx(0.03)


async def test_failed_relative_rewrite_warns_relative_stale_through_collector(monkeypatch, tmp_path):
    from app.llm.client import LLMError

    before = "없는 사건과 공급 계약으로 더 올랐습니다."
    wrapper = await _run_with_dropped_factor(monkeypatch, tmp_path, _relative_factors, {"relative": before},
                                             [_STILL_BAD, LLMError("HTTP 500")])
    assert wrapper["relative_rewrite"]["result"] == "failed"
    assert json.loads(wrapper["final_text"])["summary"]["relative"] == before
    stale = [w for w in wrapper["verify_warnings"] if w.startswith("RELATIVE_STALE")]
    assert len(stale) == 1 and "없는 사건" in stale[0] and "HTTP 500" in stale[0]


async def test_dropped_move_factor_rewrites_main_cause_through_collector(monkeypatch, tmp_path):
    def factors(payload):
        return [_linked(payload, 0, "없는 사건", ["move"], quote="원문에 없는 문장"),
                _linked(payload, 0, "공급 계약", ["move"])]

    wrapper = await _run_with_dropped_factor(
        monkeypatch, tmp_path, factors, {"main_cause": "없는 사건과 공급 계약 때문입니다.", "relative": None},
        [_STILL_BAD, (json.dumps({"main_cause": "공급 계약 때문입니다."}), {"cost": 0.01})])
    assert wrapper["main_cause_rewrite"]["result"] == "rewritten"
    assert json.loads(wrapper["final_text"])["summary"]["main_cause"] == "공급 계약 때문입니다."
    assert "relative_rewrite" not in wrapper
    assert not [w for w in wrapper["verify_warnings"] if w.startswith("MAIN_CAUSE_STALE")]


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
    assert wrapper["issue_trace_stats"]["issues_used"] == 0
    assert [w.split(":")[0] for w in wrapper["issue_trace_warnings"]] == ["ISSUE_TRACE_MISSING_URL"] * (total - 1)
    assert result["issue_trace_messages"] == {"traced": 1, "total": total}
