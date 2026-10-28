"""종목 변동 요인 보고서 러너. ③ 생성 → ④ 래핑 → ⑤ 검증 → (선택) ⑥ 적재.

    uv run python -m app.collectors.stock_analysis --input tests/fixtures/stock_analysis
    uv run python -m app.collectors.stock_analysis --input case.json --load

실행 하나가 디렉터리 하나다. 이름은 시작 시각 뒤에 uuid 앞 8자를 붙여, 같은 초에 두 러너가 시작해도
겹치지 않는다. 이미 있으면 덮어쓰지 않고 멈춘다(exist_ok=False).

    runs/<YYYYMMDD-HHMMSS>-<8자>/
      inputs/<run_id>.json   받은 입력 그대로(바이트 복사)
      parsed/<run_id>.json   실행 기록 래퍼. 적재 모듈이 읽는 파일

입력을 같이 남기는 이유: 보고서 출력에는 market 이 없어서 보고서만으로는 초과분을
다시 확인할 수 없다. 검증을 다시 돌리거나 같은 입력으로 재생성하려면 입력이 있어야 한다.
래퍼의 input_path 는 실행 디렉터리 기준 상대 경로라 runs/ 를 통째로 옮겨도 이어진다.

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

from app.core.database import SessionLocal
from app.llm.client import cost_currency, endpoint, format_cost, load_prompt
from app.repositories.stock_move_analysis import KST, insert_analysis_files
from app.services.stock_analysis.finalize import finalize
from app.services.stock_analysis.generate import (
    PROMPT_NAME,
    check_input,
    generate,
    make_run_id,
    prompt_sha256,
    report_of,
)
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


def _assign_run_ids(payloads: list[dict[str, Any]]) -> list[str]:
    """같은 종목·날짜·기준시각이 두 번 들어오면 반복 번호로 가른다. 파일이 덮어써지면 안 된다."""
    seen: Counter[str] = Counter()
    ids = []
    for payload in payloads:
        base = make_run_id(payload, 1)
        seen[base] += 1
        ids.append(base if seen[base] == 1 else make_run_id(payload, seen[base]))
    return ids


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
    (run_dir / "parsed").mkdir()

    run_ids = _assign_run_ids([payload for _, _, payload in items])
    gate = asyncio.Semaphore(concurrency)

    async def work(run_id: str, source: Path, data: bytes, payload: dict[str, Any]) -> dict:
        copied = run_dir / "inputs" / f"{run_id}.json"
        copied.write_bytes(data)
        async with gate:
            wrapper = await generate(payload, system=system, prompt_hash=prompt_hash, run_id=run_id)
            report = report_of(wrapper)
            # quote 가 원문에 없는 factor 는 검증 전에 한 번 고쳐 쓰게 하고, 그래도 없으면 뺀다.
            # 개수 상한을 넘은 보고서는 고쳐 쓰지 않는다(repair.repair_limit, 비용 상한).
            if report is not None:
                wrapper["repair_limit"] = repair_limit(report)
                repairs = await repair_quotes(report, payload, stream=wrapper["stream"], run_id=run_id)
                # 등락 층·상대 층 근거가 빠졌으면 남은 근거로 main_cause·relative 를 한 번 다시 쓰게 한다.
                for field, sentences in (("main_cause", main_cause_sentences(payload)),
                                         ("relative", RELATIVE_MAX_SENTENCES)):
                    rewrite = await rewrite_summary(report, repairs, field, stream=wrapper["stream"],
                                                    run_id=run_id, sentences=sentences)
                    if rewrite is not None:
                        wrapper[f"{field}_rewrite"] = rewrite
                        wrapper["cost"] += rewrite["cost"]
                if repairs:
                    wrapper["quote_repair"] = repairs
                    wrapper["cost"] += sum(r["cost"] for r in repairs)
                # strength·판정·main_cause 고정 문장은 러너가 정한다. 정형 보고서는 이미 러너가 정했다.
                if not wrapper.get("skipped_llm"):
                    wrapper.update(finalize(report, payload, wrapper.get("issue_trace")))
                wrapper["final_text"] = json.dumps(report, ensure_ascii=False)
        wrapper["input_path"] = copied.relative_to(run_dir).as_posix()
        wrapper["input_original_path"] = source.as_posix()
        wrapper["input_sha256"] = hashlib.sha256(data).hexdigest()
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
        out = run_dir / "parsed" / f"{run_id}.json"
        out.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8")
        counts = " ".join(f"{key}={len(wrapper[key])}" for key in WARNING_KEYS)
        print(f"  {status:6} {run_id} ({wrapper['json_status']}, "
              f"{format_cost(wrapper['cost'], wrapper['cost_currency'])}) {counts}", flush=True)
        return wrapper

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
        paths = [run_dir / "parsed" / f"{w['run_id']}.json" for w in wrappers]
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
