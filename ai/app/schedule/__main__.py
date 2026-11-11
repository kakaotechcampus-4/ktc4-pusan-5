"""명령줄: python -m app.schedule list | round <이름> [--dry-run] [--no-wait] [--force]"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime

from app.schedule.plan import ROUNDS
from app.schedule.runner import KST, real_env, run_round


def _cron_utc(rnd) -> str:
    """한국 시각을 UTC 로 바꿔 cron 의 '분 시' 로. 한국은 서머타임이 없어 9시간으로 고정이다."""
    utc = datetime.combine(date(2026, 1, 1), rnd.at, KST).astimezone(UTC)
    return f"{utc.minute} {utc.hour}"


def _list() -> None:
    print(f"{'회차':<7} {'KST':<6} {'cron(UTC) 분 시':<16} 도는 날    단계")
    for rnd in ROUNDS.values():
        steps = " → ".join(dict.fromkeys(s.name.split(":")[0] for s in rnd.plan("weekday", ["<검색어>"])))
        extra = "  (장 마감 5분 전에 맞춤)" if rnd.align_to_close else ""
        print(f"{rnd.name:<7} {rnd.at:%H:%M}  {_cron_utc(rnd):<16} {'+'.join(rnd.days):<17} {steps}{extra}")


async def _round(args: argparse.Namespace) -> int:
    from app.core.database import engine

    try:
        return await run_round(
            args.name, real_env(dry_run=args.dry_run),
            dry_run=args.dry_run, wait=not args.no_wait, force=args.force,
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.schedule", description="수집·분류 스케줄")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="회차표와 cron(UTC) 시각")
    run = sub.add_parser("round", help="회차 하나를 실행한다")
    run.add_argument("name", choices=sorted(ROUNDS))
    run.add_argument("--dry-run", action="store_true", help="무엇을 돌릴지만 보고 실행하지 않는다")
    run.add_argument("--no-wait", action="store_true", help="장 마감에 맞추려고 기다리지 않는다(시험용)")
    run.add_argument("--force", action="store_true", help="예정 시각과 어긋나도 실행한다(시험용)")
    args = parser.parse_args(argv)
    if args.cmd == "list":
        _list()
        return 0
    return asyncio.run(_round(args))


if __name__ == "__main__":
    sys.exit(main())
