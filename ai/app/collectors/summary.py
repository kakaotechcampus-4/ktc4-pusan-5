"""텔레그램 리포트 요약 배치. 검증을 통과한 결과만 저장한다.

    uv run python -m app.collectors.summary --dry-run
    uv run python -m app.collectors.summary --repair-invalid --report result.json

기본 실행은 비어 있는 요약만 채운다. --repair-invalid는 검증 실패 요약도
대상에 포함하고, --force만 기존 정상 요약을 덮어쓴다. 같은 PDF의 정상 요약은
재사용한다. 원문이 부족한 PDF는 생성 대상에서 제외한다.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.llm.client import cost_usd
from app.models import AnalystReport
from app.services.analyst.summary import build_facts, generate, grade
from app.services.analyst.telegram import has_usable_body

logger = logging.getLogger(__name__)
MIN_BODY_CHARS = 1_000
CONCURRENCY = 6


@dataclass
class Target:
    report: AnalystReport
    # 조회 이후 다른 작업이 쓴 요약은 덮어쓰지 않는다.
    previous: dict[int, str | None]
    reuse: str | None = None
    sources: dict[int, tuple[str | None, str | None]] = field(default_factory=dict)


def plan(
    rows: list[AnalystReport], *, force: bool = False,
    repair_invalid: bool = False, limit: int | None = None,
) -> list[Target]:
    """같은 PDF를 묶고, 수정할 행과 재사용 가능한 요약을 결정한다."""
    if limit is not None and limit < 1:
        raise ValueError("limit은 1 이상이어야 한다")
    groups: dict[str, list[AnalystReport]] = {}
    for row in rows:
        if row.source == "telegram":
            groups.setdefault(row.pdf_sha256 or f"id:{row.id}", []).append(row)
    targets = []
    for group in groups.values():
        usable = [r for r in group if (r.body_chars or 0) > MIN_BODY_CHARS
                  and has_usable_body(r.body_text or "")]
        if not usable:
            continue
        report = max(usable, key=lambda r: r.body_chars or 0)
        body = report.body_text or ""
        goal = build_facts(report.title or "", body)[1]
        previous = {}
        reuse = None
        for row in group:
            summary = row.summary_text
            valid = bool(summary and grade(summary, body, goal)["ok"])
            if valid and reuse is None:
                reuse = summary
            if force or not (summary or "").strip() or (repair_invalid and not valid):
                previous[row.id] = summary
        if previous:
            targets.append(Target(report, previous, None if force else reuse,
                                  {r.id: (r.body_text, r.pdf_sha256) for r in group
                                   if r.id in previous}))
    targets.sort(key=lambda t: (t.report.write_date, t.report.id), reverse=True)
    return targets[:limit] if limit is not None else targets


async def run(
    *, force: bool = False, repair_invalid: bool = False,
    limit: int | None = None, dry_run: bool = False, report_ids: list[int] | None = None,
) -> dict:
    if limit is not None and limit < 1:
        raise ValueError("limit은 1 이상이어야 한다")
    async with SessionLocal() as session:
        stmt = select(AnalystReport).where(AnalystReport.source == "telegram")
        if report_ids is not None:
            stmt = stmt.where(AnalystReport.id.in_(report_ids))
        rows = (await session.execute(stmt)).scalars().all()
        targets = plan(rows, force=force, repair_invalid=repair_invalid, limit=limit)
        # API 응답을 기다리는 동안 읽기 트랜잭션을 열어 두지 않는다.
        await session.commit()
        result = {"targets": len(targets), "saved": 0, "saved_rows": 0,
                  "reused": 0, "failed": 0, "conflicts": 0, "cost": 0.0, "failures": [],
                  "model": settings.summary_model,
                  "started_at": datetime.now(UTC).isoformat()}
        print(f"생성/재사용 대상 {len(targets)}건 (PDF 중복 제거 후)", flush=True)
        if dry_run:
            for target in targets:
                print(f"  {target.report.write_date} {target.report.title}"
                      f" ({'재사용' if target.reuse else '생성'})")
            return result

        gate = asyncio.Semaphore(CONCURRENCY)
        db_lock = asyncio.Lock()

        async def work(target: Target) -> None:
            row = target.report
            body = row.body_text or ""
            goal = build_facts(row.title or "", body)[1]
            if target.reuse:
                text, usage = target.reuse, {}
                checked = grade(text, body, goal)
            else:
                async with gate:
                    text, usage, checked = await generate(body, row.title or "")
            result["cost"] += cost_usd(usage)
            if not text or not checked["ok"]:
                result["failed"] += 1
                result["failures"].append({"ids": list(target.previous), "title": row.title,
                                           "problems": checked.get("problems", [])})
                logger.warning("%s — 저장 안 함: %s", row.title, checked.get("problems"))
                return

            saved_rows = 0
            async with db_lock:
                for report_id, previous in target.previous.items():
                    original = (AnalystReport.summary_text.is_(None) if previous is None
                                else AnalystReport.summary_text == previous)
                    previous_body, previous_sha = target.sources[report_id]
                    saved = await session.execute(update(AnalystReport).where(
                        AnalystReport.source == "telegram", AnalystReport.id == report_id,
                        original,
                        AnalystReport.body_text.is_not_distinct_from(previous_body),
                        AnalystReport.pdf_sha256.is_not_distinct_from(previous_sha),
                    ).values(summary_text=text, summary_chars=len(text)))
                    saved_rows += saved.rowcount
                # PDF 하나가 끝날 때마다 확정해 중단되어도 완료 결과를 보존한다.
                await session.commit()
            result["saved_rows"] += saved_rows
            result["conflicts"] += len(target.previous) - saved_rows
            if saved_rows:
                result["saved"] += 1
                result["reused"] += int(target.reuse is not None)
            print(f"  저장 {saved_rows}행 · {len(text)}자 · {(row.title or '')[:60]}", flush=True)

        await asyncio.gather(*(work(target) for target in targets))
    result["finished_at"] = datetime.now(UTC).isoformat()
    print(f"완료: 저장 {result['saved']} PDF / {result['saved_rows']}행 · "
          f"실패 {result['failed']} · 동시 변경 {result['conflicts']} · 약 ${result['cost']:.4f}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="텔레그램 리포트 요약 생성")
    parser.add_argument("--limit", type=int, help="최대 PDF 건수 (1 이상)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--force", action="store_true", help="정상 요약까지 다시 생성")
    modes.add_argument("--repair-invalid", action="store_true", help="검증 실패 요약도 다시 생성")
    parser.add_argument("--dry-run", action="store_true", help="대상만 조회; DB/API 변경 없음")
    parser.add_argument("--report", type=Path, help="실패 사유를 포함한 실행 결과 JSON")
    parser.add_argument("--ids", type=int, nargs="+", help="지정한 리포트 ID만 처리")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 한다")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = asyncio.run(run(force=args.force, repair_invalid=args.repair_invalid,
                             limit=args.limit, dry_run=args.dry_run, report_ids=args.ids))
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result["failed"] or result["conflicts"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
