"""종목 변동 요인 보고서 러너. ③ 생성 → ④ 래핑 → ⑤ 검증 → (선택) ⑥ 적재.

    uv run python -m app.collectors.stock_analysis --input tests/fixtures/stock_analysis
    uv run python -m app.collectors.stock_analysis --input case.json --load

실행 하나가 디렉터리 하나다.

    runs/<YYYYMMDD-HHMMSS>/
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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.database import SessionLocal
from app.llm.client import cost_currency, endpoint, format_cost, load_prompt
from app.repositories.stock_move_analysis import KST, insert_analysis_files
from app.services.stock_analysis.generate import (
    PROMPT_NAME,
    check_input,
    generate,
    make_run_id,
    prompt_sha256,
    report_of,
)
from app.services.stock_analysis.verify import code_of, verify_wrapper

logger = logging.getLogger(__name__)

# 한 건이 긴 추론 호출이라 동시에 많이 보내면 프로바이더 속도 제한(429)에 먼저 걸린다.
CONCURRENCY = 2
# prompt_version 칼럼이 String(32) 라 sha256 전체(64자)가 안 들어간다. 앞 12자만 넘기고
# 전체는 래퍼의 prompt_sha256 에 남긴다. 12자면 프롬프트 판 몇십 개 사이에서 겹칠 일이 없다.
PROMPT_VERSION_CHARS = 12


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
    run_dir = out_root / started.strftime("%Y%m%d-%H%M%S")
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "parsed").mkdir(parents=True, exist_ok=True)

    run_ids = _assign_run_ids([payload for _, _, payload in items])
    gate = asyncio.Semaphore(concurrency)

    async def work(run_id: str, source: Path, data: bytes, payload: dict[str, Any]) -> dict:
        copied = run_dir / "inputs" / f"{run_id}.json"
        copied.write_bytes(data)
        async with gate:
            wrapper = await generate(payload, system=system, prompt_hash=prompt_hash, run_id=run_id)
        wrapper["input_path"] = copied.relative_to(run_dir).as_posix()
        wrapper["input_original_path"] = source.as_posix()
        wrapper["input_sha256"] = hashlib.sha256(data).hexdigest()
        status, problems = verify_wrapper(wrapper, report_of(wrapper), payload)
        wrapper["verify_status"] = status
        wrapper["verify_problems"] = problems
        out = run_dir / "parsed" / f"{run_id}.json"
        out.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {status:6} {run_id} ({wrapper['json_status']}, "
              f"{format_cost(wrapper['cost'], wrapper['cost_currency'])})", flush=True)
        return wrapper

    wrappers = await asyncio.gather(*(
        work(run_id, path, data, payload)
        for run_id, (path, data, payload) in zip(run_ids, items, strict=True)
    ))

    # 사유는 **보고서 기준**으로 센다. 한 보고서에서 quote 가 셋 틀려도 1건이다 —
    # "몇 회차가 이 규칙에 걸렸나" 가 프롬프트를 고칠지 판단하는 숫자라서다.
    reasons: Counter[str] = Counter()
    for w in wrappers:
        reasons.update({code_of(p) for p in w["verify_problems"]})
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
