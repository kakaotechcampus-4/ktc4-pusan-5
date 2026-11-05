"""종목 변동 요인 보고서 러너. ③ 생성 → ④ 래핑 → ⑤ 검증 → (선택) ⑥ 적재.

    uv run python -m app.collectors.stock_analysis --input tests/fixtures/stock_analysis
    uv run python -m app.collectors.stock_analysis --input case.json --load

실행 하나가 디렉터리 하나다. 이름은 시작 시각 뒤에 uuid 앞 8자를 붙여, 같은 초에 두 러너가 시작해도
겹치지 않는다. 이미 있으면 덮어쓰지 않고 멈춘다(exist_ok=False).

    runs/<YYYYMMDD-HHMMSS>-<8자>/
      inputs/<run_id>.json        받은 입력 그대로(바이트 복사)
      inputs_used/<run_id>.json   실제로 생성·검증에 쓴 입력(시장 맥락을 넣고 KRX 로 덮어쓴 뒤)
      parsed/<run_id>.json        실행 기록 래퍼. 적재 모듈이 읽는 파일

입력을 같이 남기는 이유: 보고서 출력에는 market 이 없어서 보고서만으로는 초과분을
다시 확인할 수 없다. 검증을 다시 돌리거나 같은 입력으로 재생성하려면 입력이 있어야 한다.
검증을 다시 돌릴 때는 inputs_used/ 사본을 쓴다. inputs/ 사본은 KRX 로 바꾸기 전 값이라 결과가 달라질 수 있다.
래퍼의 input_path·input_used_path 는 실행 디렉터리 기준 상대 경로라 runs/ 를 통째로 옮겨도 이어진다.

생성 전에 KRX 로 시장 맥락을 계산해 입력 market_compare 칸에 넣는다(stock_analysis.market_compare).
KRX 는 실행 하나 안에서 기준일마다 한 번만 부르고(실패도 한 번), 같은 날 보고서는 그 응답을 함께 쓴다.
기준 시각이 장 마감(평소 15:30, market_compare.LATE_CLOSE 날은 그 시각) 전이면 넣지 않는다. 장 마감 이후 시장
맥락이 ok 면 입력 change_pct 와 지수 등락률을 KRX 등락률로 바꾼다(excess_pct 도 다시 계산). 모델에 보낸 칸,
실패 사유, 건너뛴 이유, 덮어쓴 원래 값은 래퍼 market_compare·market_compare_error·market_compare_skipped·
change_pct_override 에 남긴다. KRX 가 실패해도 보고서는 만들고 비교 문장만 빠진다.

보고서 하나에서 러너 코드가 예상 밖 예외를 내면(시장 맥락·고쳐 쓰기·finalize·검증) 그 보고서만 is_error 래퍼
(error_code RUNNER_ERROR, error 에 단계와 예외)로 남기고 나머지 보고서·실행 요약·적재는 계속한다.

`--load` 가 없으면 파일만 쓴다. 적재는 같은 파일을 두 번 넣지 않으므로(sha256)
파일만 먼저 쓰고 나중에 적재 모듈로 넣어도 된다.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.llm.client import cost_currency, endpoint, format_cost, load_prompt
from app.repositories.stock_move_analysis import KST, insert_analysis_files
from app.services.stock_analysis.finalize import finalize
from app.services.stock_analysis.generate import (
    PROMPT_NAME,
    _base_wrapper,
    check_input,
    generate,
    make_run_id,
    prompt_sha256,
    report_of,
)
from app.services.stock_analysis.market_compare import MarketCompare
from app.services.stock_analysis.repair import (
    RELATIVE_MAX_SENTENCES,
    repair_limit,
    repair_quotes,
    rewrite_summary,
)
from app.services.stock_analysis.verify import (
    CAPS,
    MAIN_CAUSE_STALE,
    MOVE_CASES,
    RELATIVE_STALE,
    REPAIR_SKIPPED_OVER_CAP,
    check_events,
    check_issue_trace,
    check_warnings,
    families_of,
    issue_trace_stats,
    main_cause_sentences,
    verify_wrapper,
)

logger = logging.getLogger(__name__)

# 한 건이 긴 추론 호출이라 동시에 많이 보내면 프로바이더 속도 제한(429)에 먼저 걸린다.
CONCURRENCY = 2
# prompt_version 칼럼이 String(32) 라 sha256 전체(64자)가 안 들어간다. 앞 12자만 넘기고
# 전체는 래퍼의 prompt_sha256 에 남긴다. 12자면 프롬프트 판 몇십 개 사이에서 겹칠 일이 없다.
PROMPT_VERSION_CHARS = 12
# 판정과 따로 남기는 경고 목록. 건수를 보고서마다·실행마다 찍는다.
WARNING_KEYS = ("issue_trace_warnings", "events_problems", "verify_warnings")
# 러너 코드(시장 맥락·고쳐 쓰기·finalize·검증·파일 쓰기)에서 예상 밖 예외가 난 보고서의 실패 코드.
# 그 보고서만 is_error 로 남기고 나머지는 계속 만든다(run.work).
RUNNER_ERROR = "RUNNER_ERROR"


def collect_inputs(path: Path) -> list[Path]:
    """파일이면 그 하나, 폴더면 바로 아래 *.json 을 이름순으로."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.glob("*.json") if p.is_file())
    raise ValueError(f"입력이 없다: {path}")


def load_inputs(paths: list[Path]) -> list[tuple[Path, bytes, dict[str, Any]]]:
    """전부 먼저 열어 본다. 하나라도 깨졌으면 한 건도 호출하지 않고 멈춘다 —
    앞의 건에 돈을 쓰고 나서 뒤에서 멈추면 그 실행은 반쪽이 된다."""
    loaded, problems = [], []
    for path in paths:
        data = path.read_bytes()
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"{path}: JSON 이 아니다 ({exc})")
            continue
        issues = check_input(payload)
        if issues:
            problems.append(f"{path}: " + "; ".join(issues))
            continue
        loaded.append((path, data, payload))
    if problems:
        raise ValueError("입력을 확인한다:\n  " + "\n  ".join(problems))
    if not loaded:
        raise ValueError("입력 JSON 이 하나도 없다")
    return loaded


def count_move_cases(wrappers: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    """(경우별 보고서 수, opposite 중 summary.counter 가 null 이 아닌 수).

    두 번째 숫자는 opposite 날 factors 의 direction_match 를 change_pct 와 excess_pct 중
    무엇에 맞출지 정할 근거다. 지금은 change_pct 기준이라 차이를 만든 재료가 counter 로
    밀려난다. 보고서를 열 수 없는 회차는 counter 를 알 수 없어 세지 않는다.
    """
    cases = {case: 0 for case in (*MOVE_CASES, "null")}
    opposite_with_counter = 0
    for w in wrappers:
        case = w.get("move_case") or "null"
        cases[case] += 1
        if case != "opposite":
            continue
        report = report_of(w)
        summary = report.get("summary") if report else None
        if isinstance(summary, dict) and summary.get("counter") is not None:
            opposite_with_counter += 1
    return cases, opposite_with_counter


def count_market_compare(wrappers: list[dict[str, Any]]) -> dict[str, int]:
    """시장 맥락 status 별 보고서 수. 칸이 null 이면 장 마감 전은 before_close, 그 밖(KRX 호출·계산 실패)은 failed."""
    def status(w: dict[str, Any]) -> str:
        if w.get("market_compare"):
            return w["market_compare"]["status"]
        return "before_close" if w.get("market_compare_skipped") else "failed"

    counts: Counter[str] = Counter(status(w) for w in wrappers)
    return dict(sorted(counts.items()))


def count_market_compare_errors(wrappers: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    """(시장 맥락 실패의 예외 종류별 보고서 수, 그중 예상 밖 예외인 보고서 수)."""
    kinds: Counter[str] = Counter(w["market_compare_error_type"] for w in wrappers
                                  if w.get("market_compare_error_type"))
    return dict(sorted(kinds.items())), sum(bool(w.get("market_compare_unexpected")) for w in wrappers)


def _assign_run_ids(payloads: list[dict[str, Any]]) -> list[str]:
    """같은 종목·날짜·기준시각이 두 번 들어오면 반복 번호로 가른다. 파일이 덮어써지면 안 된다."""
    seen: Counter[str] = Counter()
    ids = []
    for payload in payloads:
        base = make_run_id(payload, 1)
        seen[base] += 1
        ids.append(base if seen[base] == 1 else make_run_id(payload, seen[base]))
    return ids


def runner_error_wrapper(
    progress: dict[str, Any], exc: Exception, *, run_id: str, prompt_hash: str, run_dir: Path,
    source: Path, data: bytes,
) -> dict[str, Any]:
    """러너 코드에서 예상 밖 예외가 난 보고서 하나의 래퍼. 생성까지 마쳤으면 그 래퍼(비용·사용량)를 살린다.

    보고서는 반쯤 고쳐졌을 수 있어 믿지 않는다. final_text 를 비워 적재 때 parse_failed 가 되고, 판정은
    RUNNER_ERROR 로 failed 다. 예외의 원인이 검증 함수일 수도 있으므로 여기서는 검증·점검 함수를 다시 부르지 않는다.
    """
    wrapper = progress["wrapper"] or _base_wrapper(progress["payload"], prompt_hash=prompt_hash,
                                                   run_id=run_id)
    error = f"{progress['stage']}: {type(exc).__name__}: {str(exc)[:300]}"
    wrapper.update(
        is_error=True, error_code=RUNNER_ERROR, error=error, final_text="",
        input_path=(Path("inputs") / f"{run_id}.json").as_posix(),
        input_used_path=(Path("inputs_used") / f"{run_id}.json").as_posix(),
        input_original_path=source.as_posix(), input_sha256=hashlib.sha256(data).hexdigest(),
        verify_status="failed", verify_problems=[f"{RUNNER_ERROR}: {error}"],
        events_status="missing", events_problems=[], verify_warnings=[], issue_trace_warnings=[],
        issue_trace_stats=None,
    )
    return wrapper


async def run(
    input_path: Path, *, out_root: Path = Path("runs"), concurrency: int = CONCURRENCY,
    load: bool = False,
) -> dict[str, Any]:
    if concurrency < 1:
        raise ValueError("concurrency 는 1 이상이어야 한다")
    items = load_inputs(collect_inputs(input_path))
    # 키·주소가 빠졌으면 디렉터리를 만들기 전에 멈춘다. RuntimeError 로 올라간다.
    endpoint()

    system = load_prompt(PROMPT_NAME)
    prompt_hash = prompt_sha256()
    started = datetime.now(KST)
    run_dir = out_root / f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "inputs").mkdir()
    (run_dir / "inputs_used").mkdir()
    (run_dir / "parsed").mkdir()

    run_ids = _assign_run_ids([payload for _, _, payload in items])
    gate = asyncio.Semaphore(concurrency)

    async def work(run_id: str, source: Path, data: bytes, payload: dict[str, Any]) -> dict:
        """보고서 하나. 어느 단계에서 예외가 나도 이 보고서만 실행 오류 래퍼로 남기고 돌아온다 —
        asyncio.gather 로 함께 도는 다른 보고서·실행 요약·--load 가 멈추면 안 된다."""
        progress: dict[str, Any] = {"stage": "입력 복사", "payload": payload, "wrapper": None}
        try:
            wrapper = await _work(run_id, source, data, payload, progress)
        except Exception as exc:  # 종류와 단계는 래퍼 error 에 남긴다
            logger.error("%s: %s 단계에서 예상 밖 예외, 이 보고서만 실행 오류로 남긴다", run_id,
                         progress["stage"], exc_info=exc)
            wrapper = runner_error_wrapper(progress, exc, run_id=run_id, prompt_hash=prompt_hash,
                                           run_dir=run_dir, source=source, data=data)
        out = run_dir / "parsed" / f"{run_id}.json"
        try:
            out.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            # 파일이 없으면 --load 도 이 보고서를 건너뛴다(아래 paths)
            logger.error("%s: parsed 파일을 쓰지 못했다: %s", run_id, exc)
            wrapper["parsed_write_error"] = f"{type(exc).__name__}: {exc}"
        counts = " ".join(f"{key}={len(wrapper[key])}" for key in WARNING_KEYS)
        print(f"  {wrapper['verify_status']:6} {run_id} ({wrapper['json_status']}, "
              f"{format_cost(wrapper['cost'], wrapper['cost_currency'])}) {counts}", flush=True)
        return wrapper

    async def _work(run_id: str, source: Path, data: bytes, payload: dict[str, Any],
                    progress: dict[str, Any]) -> dict:
        copied = run_dir / "inputs" / f"{run_id}.json"
        copied.write_bytes(data)
        used = run_dir / "inputs_used" / f"{run_id}.json"
        async with gate:
            # 장 마감 전이거나 실패하면 칸이 null 이고 보고서는 그대로 만든다. 장 마감 이후 ok 면 change_pct 가 KRX
            # 등락률로 바뀐다. 받은 입력 dict 는 바꾸지 않고, 이후 생성·검증은 바뀐 입력으로 한다.
            progress["stage"] = "시장 맥락"
            payload, compare_fields = await compare_for.apply(payload)
            progress["payload"] = payload
            used.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            progress["stage"] = "보고서 생성"
            wrapper = await generate(payload, system=system, prompt_hash=prompt_hash, run_id=run_id)
            wrapper.update(compare_fields)
            progress["wrapper"] = wrapper
            report = report_of(wrapper)
            # quote 가 원문에 없는 factor 는 검증 전에 한 번 고쳐 쓰게 하고, 그래도 없으면 뺀다.
            # 개수 상한을 넘은 보고서는 고쳐 쓰지 않는다(repair.repair_limit, 비용 상한).
            if report is not None:
                progress["stage"] = "quote 고쳐 쓰기"
                wrapper["repair_limit"] = repair_limit(report)
                repairs = await repair_quotes(report, payload, stream=wrapper["stream"], run_id=run_id)
                # 등락 층·상대 층 근거가 빠졌으면 남은 근거로 main_cause·relative 를 한 번 다시 쓰게 한다.
                # relative 의 코스피·그룹 비교 문장이 지워지지 않게 모델에 보낸 market_compare 와 종목명을 함께 준다.
                for field, sentences in (("main_cause", main_cause_sentences(payload)),
                                         ("relative", RELATIVE_MAX_SENTENCES)):
                    rewrite = await rewrite_summary(report, repairs, field, stream=wrapper["stream"],
                                                    run_id=run_id, sentences=sentences,
                                                    market_compare=payload.get("market_compare"),
                                                    stock=payload.get("stock"))
                    if rewrite is not None:
                        wrapper[f"{field}_rewrite"] = rewrite
                        wrapper["cost"] += rewrite["cost"]
                if repairs:
                    wrapper["quote_repair"] = repairs
                    wrapper["cost"] += sum(r["cost"] for r in repairs)
                # strength·판정·main_cause 고정 문장은 러너가 정한다. 정형 보고서는 이미 러너가 정했다.
                if not wrapper.get("skipped_llm"):
                    progress["stage"] = "finalize"
                    wrapper.update(finalize(report, payload, wrapper.get("issue_trace")))
                wrapper["final_text"] = json.dumps(report, ensure_ascii=False)
        wrapper["input_path"] = copied.relative_to(run_dir).as_posix()
        wrapper["input_used_path"] = used.relative_to(run_dir).as_posix()
        wrapper["input_original_path"] = source.as_posix()
        wrapper["input_sha256"] = hashlib.sha256(data).hexdigest()
        progress["stage"] = "검증"
        status, problems = verify_wrapper(wrapper, report, payload)
        wrapper["verify_status"] = status
        wrapper["verify_problems"] = problems
        # 검수용 events 칸. 판정(verify_status)과 섞지 않는다(verify.check_events).
        wrapper["events_status"], wrapper["events_problems"] = check_events(report)
        trace = wrapper.get("issue_trace")
        # 실패는 아니지만 검수자가 볼 것(verify.check_warnings). 판정과 섞지 않는다.
        wrapper["verify_warnings"] = check_warnings(report, payload, trace, wrapper.get("strength_recomputed"))
        for field, code, layer in (("main_cause", MAIN_CAUSE_STALE, "등락 층"), ("relative", RELATIVE_STALE, "상대 층")):
            rewrite = wrapper.get(f"{field}_rewrite")
            if rewrite is not None and rewrite["result"] == "failed":
                wrapper["verify_warnings"].append(
                    f"{code}: {layer} 근거 {rewrite['dropped']} 를 뺐는데 {field} 를 다시 쓰지 못했다 ({rewrite['error']})")
        limit = wrapper.get("repair_limit")
        if limit is not None and limit["hit"]:
            wrapper["verify_warnings"].append(
                f"{REPAIR_SKIPPED_OVER_CAP}: factors {limit['factors']}개(최대 {CAPS['factors']}), background "
                f"{limit['background']}개(최대 {CAPS['background']}) — quote 고쳐 쓰기를 하지 않았다")
        # issue_trace 가 messages 칸 메시지를 빠뜨렸거나(ISSUE_TRACE_MISSING_URL) events 가 issue_trace 에 없는 이슈 id 를
        # 가리키면(ISSUE_ID_UNKNOWN) 경고만 남긴다. 판정과 섞지 않는다. 관련 유형별 수는 stats 에서만 센다.
        wrapper["issue_trace_warnings"] = check_issue_trace(trace, report, payload)
        wrapper["issue_trace_stats"] = issue_trace_stats(trace, report, payload)
        return wrapper

    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        # 기준일별 KRX 응답을 이 실행이 끝날 때까지 함께 쓴다
        compare_for = MarketCompare(client)
        wrappers = await asyncio.gather(*(
            work(run_id, path, data, payload)
            for run_id, (path, data, payload) in zip(run_ids, items, strict=True)
        ))

    # 사유는 **보고서 기준·계열 단위**로 센다. 한 보고서에서 quote 가 셋 틀려도 1건이고,
    # 한 실수로 함께 나오는 코드(FLAT_MOVE_VERDICT + FLAT_MOVE_FACTORS 등)도 1건이다 —
    # "몇 회차가 이 실수를 했나" 가 프롬프트를 고칠지 판단하는 숫자라서다.
    # 코드별 상세는 래퍼의 verify_problems 에 그대로 있다.
    reasons: Counter[str] = Counter()
    for w in wrappers:
        reasons.update(families_of(w["verify_problems"]))
    move_cases, opposite_with_counter = count_move_cases(wrappers)
    compare_errors, compare_unexpected = count_market_compare_errors(wrappers)
    result = {
        "run_dir": str(run_dir),
        "total": len(wrappers),
        "passed": sum(w["verify_status"] == "passed" for w in wrappers),
        "failed": sum(w["verify_status"] == "failed" for w in wrappers),
        "errors": sum(bool(w["is_error"]) for w in wrappers),
        "cost": sum(w["cost"] for w in wrappers),
        # 한 실행은 프로바이더 하나라 통화도 하나다.
        "currency": cost_currency(),
        "reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "move_cases": move_cases,
        "opposite_with_counter": opposite_with_counter,
        # 검수용 events 칸의 상태별 건수. passed·failed 와 따로 센다.
        "events": {s: sum(w["events_status"] == s for w in wrappers)
                   for s in ("passed", "failed", "missing")},
        # 경고가 하나라도 붙은 보고서 수. passed·failed 와 따로 센다.
        "warned": sum(bool(w["verify_warnings"]) for w in wrappers),
        # 판정과 따로 남기는 경고의 건수 합(보고서 수가 아니라 경고 수).
        "warning_counts": {key: sum(len(w[key]) for w in wrappers) for key in WARNING_KEYS},
        # LLM 을 다시 부른 회차 수(JSON 이 안 열림 / 판단하지 않는 층에 원인을 닮).
        "retried": {key: sum(bool((w.get(key) or {}).get("retried")) for w in wrappers)
                    for key in ("json_retry", "judge_retry")},
        # 직접 언급 메시지가 0건이라 LLM 을 부르지 않고 정형 보고서를 낸 회차 수(generate.canned_report).
        "skipped_llm": sum(bool(w.get("skipped_llm")) for w in wrappers),
        # 시장 맥락 status 별 보고서 수. 칸이 null 인 것은 before_close(장 마감 전)·failed(KRX 호출·계산 실패).
        "market_compare": count_market_compare(wrappers),
        # 입력 change_pct 를 KRX 등락률로 덮어쓴 보고서 수(장 마감 이후 시장 맥락 ok).
        "change_pct_overridden": sum(w.get("change_pct_override") is not None for w in wrappers),
        # 시장 맥락 실패의 예외 종류별 보고서 수와, 그중 예상 밖 예외(코드 버그·KRX 응답 모양 변화)인 보고서 수.
        "market_compare_errors": compare_errors,
        "market_compare_unexpected": compare_unexpected,
        # issue_trace 에 오른 메시지 수 / 입력 메시지 수. issue_trace 가 있는 보고서만 더한다.
        "issue_trace_messages": {
            k: sum(w["issue_trace_stats"][f"messages_{k}"] for w in wrappers if w["issue_trace_stats"])
            for k in ("traced", "total")},
        "loaded": None,
    }

    if load:
        verdicts = {
            w["run_id"]: (w["verify_status"], "\n".join(w["verify_problems"]) or None)
            for w in wrappers
        }
        paths = [run_dir / "parsed" / f"{w['run_id']}.json" for w in wrappers
                 if not w.get("parsed_write_error")]
        async with SessionLocal() as session:
            inserted = await insert_analysis_files(
                session, paths, verdicts=verdicts, generated_at=started,
                prompt_version=prompt_hash[:PROMPT_VERSION_CHARS],
            )
            # 실행 하나를 한 트랜잭션으로 본다. 반만 들어간 실행은 검수 때 헷갈린다.
            await session.commit()
        result["loaded"] = len(inserted)

    loaded = "" if result["loaded"] is None else f" · 적재 {result['loaded']}"
    print(f"완료: 보고서 {result['total']}건 · 검증 통과 {result['passed']}건"
          f" · 검증 실패 보고서 {result['failed']}건 (그중 실행 오류 {result['errors']}건)"
          f" · {format_cost(result['cost'], result['currency'])}{loaded} · {run_dir}")
    # 한 보고서가 여러 사유로 실패할 수 있어 합이 실패 보고서 수보다 클 수 있다.
    # 헷갈리지 않게 줄을 나누고 기준을 적어 둔다.
    print("사유별 건수 (사유에 걸린 보고서 수, 한 보고서가 여러 사유에 들 수 있음): "
          + (", ".join(f"{c}={n}" for c, n in result["reasons"].items()) or "없음"))
    print("경우별 건수: " + ", ".join(
        f"{c}={n}" + (f" (그중 counter 있음 {opposite_with_counter})" if c == "opposite" else "")
        for c, n in move_cases.items()))
    print("events 검사 (판정과 별도): "
          + ", ".join(f"{s}={n}" for s, n in result["events"].items()))
    traced = result["issue_trace_messages"]
    print(f"issue_trace 에 오른 메시지: {traced['traced']} / 입력 {traced['total']}")
    print("경고 건수 (판정과 별도): "
          + ", ".join(f"{k}={n}" for k, n in result["warning_counts"].items()))
    print("다시 부른 회차: " + ", ".join(f"{k}={n}" for k, n in result["retried"].items())
          + f" · LLM 없이 정형 보고서: {result['skipped_llm']}")
    print("시장 맥락 (ok 밖은 비교 문장 없이 만듦): "
          + ", ".join(f"{s}={n}" for s, n in result["market_compare"].items())
          + f" · change_pct 를 KRX 등락률로 바꿈: {result['change_pct_overridden']}")
    if compare_errors:
        print("시장 맥락 실패 종류: " + ", ".join(f"{k}={n}" for k, n in compare_errors.items())
              + (f" · 예상 밖 예외 {compare_unexpected}건 — 로그의 traceback 을 확인한다" if compare_unexpected else ""))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="종목 변동 요인 보고서 생성·검증")
    parser.add_argument("--input", type=Path, required=True, help="입력 JSON 파일 또는 폴더")
    parser.add_argument("--load", action="store_true", help="검증 결과와 함께 DB 에 적재")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY,
                        help=f"동시 호출 수 (기본 {CONCURRENCY})")
    parser.add_argument("--out", type=Path, default=Path("runs"), help="실행 디렉터리의 부모")
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency 는 1 이상이어야 한다")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = asyncio.run(run(args.input, out_root=args.out, concurrency=args.concurrency,
                                 load=args.load))
    except (ValueError, RuntimeError) as exc:
        print(exc)
        raise SystemExit(1) from None
    # 검증 실패는 데이터라 정상 종료다. 호출 자체가 실패한 건만 알린다.
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
