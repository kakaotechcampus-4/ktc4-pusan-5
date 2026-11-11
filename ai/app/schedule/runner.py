"""회차 하나를 실행한다.

cron 은 UTC 고정 시각에 매일 이 회차를 부르고, 오늘이 돌릴 날인지는 여기서 한국 시간으로 판단한다.
서버 시간대를 바꾸지 않는 이유는 배포 스크립트의 백업 파일 이름·로그 시각이 서버 시간(UTC)을 쓰기 때문이다.

    1. 이 회차가 도는 날(평일/주말)인가
    2. 예정 시각과 크게 어긋나지 않았나(cron 시간대를 잘못 적은 실수 방어)
    3. 평일인데 휴장일이면 건너뛴다(market_calendar, 오늘 행이 없으면 평일 규칙)
    4. 이미 다른 회차가 돌고 있으면 건너뛴다(DB advisory lock. 메모리가 모자라 동시에 돌리지 않는다)
    5. 장 마감에 맞추는 회차는 그날 마감 5분 전까지 기다린다(수능일 등 마감이 늦춰지는 날)
    6. 단계를 순서대로 돌린다. 한 단계가 실패하거나 시간을 넘겨도 다음 단계는 계속한다

종료 코드: 실패·시간 초과·키 없음이 하나라도 있으면 1, 아니면 0. 건너뜀(휴장일·범위 꺼짐·시한 지남)은 0.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.scope import CollectionScope, ScopeError
from app.schedule.plan import ROUNDS, WEEKDAY, WEEKEND, Round, Step, python_argv

KST = ZoneInfo("Asia/Seoul")

# 예정 시각과 이만큼 넘게 어긋나면 시간대를 잘못 적은 것으로 보고 멈춘다(--force 로 무시).
DRIFT = timedelta(minutes=30)
# 장 마감에 맞추는 회차: 마감 5분 전에 시작하고, 마감 30초 전까지만 수집 단계를 시작한다.
ALIGN_BEFORE_CLOSE = timedelta(minutes=5)
DEADLINE_BEFORE_CLOSE = timedelta(seconds=30)
# 마감을 기다리는 최대 시간. 이보다 길게 기다려야 하면 날짜·마감 시각이 이상한 것이다.
MAX_WAIT = timedelta(hours=3)
# 회차끼리 겹치지 않게 하는 advisory lock. backend 수집기는 4927105·4927106 을 쓴다.
LOCK_ID = 4927107

OK, FAILED, TIMEOUT, MISSING_KEY = "ok", "failed", "timeout", "missing_key"
SKIP_SCOPE, SKIP_DEADLINE = "skipped_scope", "skipped_deadline"
BAD = {FAILED, TIMEOUT, MISSING_KEY}


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""
    seconds: int = 0


@dataclass
class Env:
    """바깥 세상과 닿는 부분. 시험에서는 이것만 바꿔 끼운다."""

    now: Callable[[], datetime]
    sleep: Callable[[float], Awaitable[None]]
    is_open: Callable[[date], Awaitable[bool | None]]  # market_calendar. 행이 없으면 None
    load_scope: Callable[[], CollectionScope]
    missing: Callable[[tuple[str, ...]], list[str]]  # 비어 있는 설정 이름
    execute: Callable[[Step, float], Awaitable[int | None]]  # 종료 코드. 시간 초과면 None
    lock: Callable[[], AbstractAsyncContextManager[bool]]
    close_of: Callable[[date], time]  # 그날 장 마감 시각(KST)
    out: Callable[[str], None] = print


def kind_of(day: date) -> str:
    return WEEKEND if day.weekday() >= 5 else WEEKDAY


def _say(env: Env, text: str) -> None:
    env.out(f"{env.now().astimezone(KST):%H:%M:%S} {text}")


def _decide(step: Step, scope: CollectionScope, env: Env) -> tuple[str, str]:
    """이 단계를 돌릴지. ("run", "") 이거나 건너뛰는 상태와 이유."""
    if step.source and not scope.source(step.source).enabled:
        return SKIP_SCOPE, f"수집 범위에서 꺼져 있음({step.source})"
    if step.any_scope and not any(s.enabled for s in scope.sources.values()):
        return SKIP_SCOPE, "켜진 수집 출처가 없음"
    if step.needs:
        missing = env.missing(step.needs)
        if missing:
            return MISSING_KEY, "설정 없음: " + ", ".join(missing)
    return "run", ""


def _print_plan(env: Env, rnd: Round, steps: list[Step], scope: CollectionScope) -> None:
    for step in steps:
        status, why = _decide(step, scope, env)
        mark = "▶" if status == "run" else "·"
        suffix = "" if status == "run" else f"  ({status}: {why})"
        _say(env, f"  {mark} {step.name}  python {' '.join(step.argv)}{suffix}")


async def run_round(
    name: str, env: Env, *, dry_run: bool = False, wait: bool = True, force: bool = False,
) -> int:
    rnd = ROUNDS[name]
    now = env.now().astimezone(KST)
    day = now.date()
    kind = kind_of(day)
    _say(env, f"[{name}] {day} {kind} 회차 시작(예정 {rnd.at:%H:%M} KST)")

    if kind not in rnd.days:
        _say(env, f"이 회차는 {'·'.join(rnd.days)} 에만 돈다. 건너뜀")
        return 0

    planned = datetime.combine(day, rnd.at, KST)
    if abs(now - planned) > DRIFT and not force and not dry_run:
        _say(env, f"예정 시각 {rnd.at:%H:%M} 과 {abs(now - planned)} 어긋남. cron 시간대 설정을 확인하세요"
                  "(무시하려면 --force). 멈춤")
        return 1

    if kind == WEEKDAY:
        is_open = await env.is_open(day)
        if is_open is None:
            _say(env, "market_calendar 에 오늘 행이 없어 평일 규칙으로 판단")
        elif not is_open:
            _say(env, "휴장일이라 건너뜀(market_calendar)")
            return 0

    try:
        scope = env.load_scope()
    except ScopeError as exc:
        _say(env, f"수집 범위를 읽지 못함: {exc}")
        return 1
    queries = sorted(scope.source("naver_news").allowed)
    steps = rnd.plan(kind, queries)
    if dry_run:
        _say(env, "dry-run: 아래 단계를 돌린다(실행하지 않음)")
        _print_plan(env, rnd, steps, scope)
        if rnd.align_to_close:
            close = env.close_of(day)
            _say(env, f"  장 마감 {close:%H:%M} → {datetime.combine(day, close, KST) - ALIGN_BEFORE_CLOSE:%H:%M} 에 시작")
        return 0

    async with env.lock() as got:
        if not got:
            _say(env, "다른 회차가 아직 실행 중이라 건너뜀(DB lock). 앞 회차가 오래 걸린 것이니 로그를 확인하세요")
            return 1
        return await _run_steps(rnd, steps, scope, env, day, wait)


async def _run_steps(
    rnd: Round, steps: list[Step], scope: CollectionScope, env: Env, day: date, wait: bool,
) -> int:
    deadline: datetime | None = None
    if rnd.align_to_close:
        close_at = datetime.combine(day, env.close_of(day), KST)
        start_at = close_at - ALIGN_BEFORE_CLOSE
        deadline = close_at - DEADLINE_BEFORE_CLOSE
        remaining = start_at - env.now()
        if remaining > timedelta(0):
            if remaining > MAX_WAIT:
                _say(env, f"장 마감 {close_at:%H:%M} 까지 {remaining} 를 기다려야 해서 멈춤(날짜·마감 시각 확인)")
                return 1
            if wait:
                _say(env, f"장 마감 {close_at:%H:%M} 에 맞춰 {start_at:%H:%M} 까지 {remaining} 기다림")
                await env.sleep(remaining.total_seconds())
            else:
                _say(env, "--no-wait: 기다리지 않고 바로 시작")

    results: list[Result] = []
    for step in steps:
        status, why = _decide(step, scope, env)
        if status != "run":
            results.append(Result(step.name, status, why))
            continue
        timeout = float(step.timeout)
        if step.collect and deadline is not None:
            left = (deadline - env.now()).total_seconds()
            if left <= 0:
                results.append(Result(step.name, SKIP_DEADLINE, "장 마감 직전이라 시작하지 않음"))
                continue
            timeout = min(timeout, left)
        began = env.now()
        _say(env, f"▶ {step.name}")
        code = await env.execute(step, timeout)
        seconds = int((env.now() - began).total_seconds())
        if code == 0:
            results.append(Result(step.name, OK, "", seconds))
        elif code is None:
            results.append(Result(step.name, TIMEOUT, f"{int(timeout)}초 안에 끝나지 않아 중단", seconds))
        else:
            results.append(Result(step.name, FAILED, f"종료 코드 {code}", seconds))

    _say(env, f"[{rnd.name}] 결과")
    for r in results:
        env.out(f"    {r.status:<17} {r.name:<28} {r.seconds:>4}s  {r.detail}".rstrip())
    bad = [r for r in results if r.status in BAD]
    skipped = [r for r in results if r.status in (SKIP_SCOPE, SKIP_DEADLINE)]
    _say(env, f"[{rnd.name}] 끝: 성공 {sum(r.status == OK for r in results)} · 문제 {len(bad)} · 건너뜀 {len(skipped)}")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# 실제 환경

def real_env(*, dry_run: bool) -> Env:
    from sqlalchemy import text

    from app.core.config import settings
    from app.core.database import SessionLocal, engine
    from app.core.scope import load_scope

    async def is_open(day: date) -> bool | None:
        try:
            async with SessionLocal() as session:
                row = (await session.execute(
                    text("SELECT is_open FROM market_calendar WHERE day = :day"), {"day": day},
                )).first()
        except Exception:  # noqa: BLE001 — 표가 없거나 DB 를 못 읽으면 평일 규칙으로 간다
            return None
        return None if row is None else bool(row[0])

    @asynccontextmanager
    async def lock():
        if dry_run:  # 실행하지 않으니 DB 를 쓰지 않는다
            yield True
            return
        async with engine.connect() as conn:
            got = bool(await conn.scalar(text(f"SELECT pg_try_advisory_lock({LOCK_ID})")))
            try:
                yield got
            finally:
                if got:
                    await conn.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))

    async def execute(step: Step, timeout: float) -> int | None:
        proc = await asyncio.create_subprocess_exec(*python_argv(step))
        try:
            return await asyncio.wait_for(proc.wait(), timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return None

    def close_of(day: date) -> time:
        from app.services.stock_analysis.market_compare import market_close

        return market_close(day)

    def missing(names: tuple[str, ...]) -> list[str]:
        return [n.upper() for n in names if not getattr(settings, n, None)]

    return Env(
        now=lambda: datetime.now(KST),
        sleep=asyncio.sleep,
        is_open=is_open,
        load_scope=load_scope,
        missing=missing,
        execute=execute,
        lock=lock,
        close_of=close_of,
        out=lambda line: print(line, flush=True),
    )
