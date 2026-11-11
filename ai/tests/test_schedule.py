"""수집·분류 스케줄(app/schedule) 시험. DB·LLM·네트워크 없이 시계와 실행기를 가짜로 바꿔 돌린다."""

from __future__ import annotations

import re
import time as clock
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from app.core.scope import CollectionScope, ScopeError, SourceScope
from app.schedule.__main__ import _cron_utc
from app.schedule.plan import ROUNDS, WEEKDAY, WEEKEND, Step, news_steps
from app.schedule.runner import KST, Env, kind_of, real_env, run_round

TUE = datetime(2026, 11, 10, tzinfo=KST)  # 화요일
SAT = datetime(2026, 11, 14, tzinfo=KST)  # 토요일
SUNEUNG = datetime(2026, 11, 19, tzinfo=KST)  # 수능일. 장 마감 16:30

ALL_SOURCES = ("dart", "naver_research", "telegram_web", "telegram_client", "naver_news")


def at(day: datetime, hh: int, mm: int, ss: int = 0) -> datetime:
    return day.replace(hour=hh, minute=mm, second=ss)


def scope_with(enabled: tuple[str, ...], queries: tuple[str, ...] = ("삼성전자", "SK하이닉스")) -> CollectionScope:
    sources = {
        name: SourceScope(name, enabled=True, allowed=frozenset(queries) if name == "naver_news" else frozenset())
        for name in enabled
    }
    return CollectionScope(sources=sources)


@dataclass
class Harness:
    """가짜 환경. 시계는 sleep·execute 가 움직인다."""

    start: datetime
    enabled: tuple[str, ...] = ALL_SOURCES
    queries: tuple[str, ...] = ("삼성전자", "SK하이닉스")
    open_day: bool | None = True
    missing_keys: tuple[str, ...] = ()
    lock_free: bool = True
    close: time = time(15, 30)
    durations: dict[str, float] = field(default_factory=dict)
    codes: dict[str, int] = field(default_factory=dict)
    scope_error: str | None = None
    lines: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    timeouts: dict[str, float] = field(default_factory=dict)
    slept: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.t = self.start

    async def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += timedelta(seconds=seconds)

    async def _is_open(self, day) -> bool | None:
        return self.open_day

    def _scope(self) -> CollectionScope:
        if self.scope_error:
            raise ScopeError(self.scope_error)
        return scope_with(self.enabled, self.queries)

    async def _execute(self, step: Step, timeout: float) -> int | None:
        self.ran.append(step.name)
        self.timeouts[step.name] = timeout
        wanted = self.durations.get(step.name, 10)
        if wanted > timeout:  # 시간 초과: 제한 시간만큼 쓰고 중단
            self.t += timedelta(seconds=timeout)
            return None
        self.t += timedelta(seconds=wanted)
        return self.codes.get(step.name, 0)

    def _lock(self):
        @asynccontextmanager
        async def lock():
            yield self.lock_free

        return lock()

    def env(self) -> Env:
        return Env(
            now=lambda: self.t,
            sleep=self._sleep,
            is_open=self._is_open,
            load_scope=self._scope,
            missing=lambda names: [n.upper() for n in names if n in self.missing_keys],
            execute=self._execute,
            lock=self._lock,
            close_of=lambda day: self.close,
            out=self.lines.append,
        )

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


async def go(name: str, h: Harness, **kwargs) -> int:
    return await run_round(name, h.env(), **kwargs)


# ---------------------------------------------------------------- 회차표

def test_회차표_시각과_cron_UTC():
    assert list(ROUNDS) == ["r0900", "r1100", "r1300", "r1520", "r1525", "r1800"]
    assert {n: _cron_utc(r) for n, r in ROUNDS.items()} == {
        "r0900": "0 0", "r1100": "0 2", "r1300": "0 4", "r1520": "20 6", "r1525": "25 6", "r1800": "0 9",
    }


def test_장_마감에_맞추는_회차는_15시25분_하나뿐():
    assert [n for n, r in ROUNDS.items() if r.align_to_close] == ["r1525"]


def test_요일_종류():
    assert kind_of(TUE.date()) == WEEKDAY
    assert kind_of(SAT.date()) == WEEKEND


def test_뉴스는_검색어마다_한_단계():
    assert [s.name for s in news_steps(["삼성전자", "NAVER"])] == ["news:삼성전자", "news:NAVER"]
    assert news_steps([]) == []


# ---------------------------------------------------------------- 평일 회차

async def test_평일_아침은_수집_순서대로_돌고_분류가_마지막():
    h = Harness(at(TUE, 9, 0))
    assert await go("r0900", h) == 0
    assert h.ran == ["dart", "research", "telegram_web", "news:SK하이닉스", "news:삼성전자",
                     "telegram_pdf", "register", "classify"]


async def test_15시20분은_리서치만():
    h = Harness(at(TUE, 15, 20))
    assert await go("r1520", h) == 0
    assert h.ran == ["research"]


async def test_낮_회차는_리서치가_없다():
    for name, hh in (("r1100", 11), ("r1300", 13)):
        h = Harness(at(TUE, hh, 0))
        await go(name, h)
        assert "research" not in h.ran and h.ran[0] == "dart"


async def test_평일_18시는_DART가_있고_주말_18시는_없다():
    weekday = Harness(at(TUE, 18, 0))
    await go("r1800", weekday)
    assert weekday.ran[0] == "dart"

    weekend = Harness(at(SAT, 18, 0))
    assert await go("r1800", weekend) == 0
    assert weekend.ran[0] == "telegram_web"
    assert "dart" not in weekend.ran and "research" not in weekend.ran


async def test_주말에는_평일_회차가_돌지_않는다():
    for name, hh, mm in (("r0900", 9, 0), ("r1100", 11, 0), ("r1520", 15, 20), ("r1525", 15, 25)):
        h = Harness(at(SAT, hh, mm))
        assert await go(name, h) == 0
        assert h.ran == []
        assert "건너뜀" in h.text


# ---------------------------------------------------------------- 휴장일

async def test_평일_휴장일은_통째로_건너뛴다():
    h = Harness(at(TUE, 9, 0), open_day=False)
    assert await go("r0900", h) == 0
    assert h.ran == []
    assert "휴장일" in h.text


async def test_평일_18시도_휴장일이면_건너뛴다():
    h = Harness(at(TUE, 18, 0), open_day=False)
    assert await go("r1800", h) == 0
    assert h.ran == []


async def test_달력에_행이_없으면_평일_규칙으로_돈다():
    h = Harness(at(TUE, 9, 0), open_day=None)
    assert await go("r0900", h) == 0
    assert h.ran[0] == "dart"
    assert "평일 규칙" in h.text


async def test_주말_18시는_휴장_여부를_보지_않는다():
    h = Harness(at(SAT, 18, 0), open_day=False)  # 주말은 늘 휴장이지만 수집한다
    assert await go("r1800", h) == 0
    assert h.ran[0] == "telegram_web"


# ---------------------------------------------------------------- 범위·키·실패

async def test_범위에서_꺼진_출처는_건너뛰고_성공으로_센다():
    h = Harness(at(TUE, 9, 0), enabled=("telegram_web",))
    assert await go("r0900", h) == 0
    assert h.ran == ["telegram_web", "register", "classify"]
    assert "skipped_scope" in h.text


async def test_모든_출처가_꺼져_있으면_분류도_돌지_않는다():
    h = Harness(at(TUE, 9, 0), enabled=())
    assert await go("r0900", h) == 0
    assert h.ran == []  # 수집은 안 하는데 분류 비용만 쓰지 않는다
    assert "켜진 수집 출처가 없음" in h.text


async def test_켜진_출처가_하나라도_있으면_분류가_돈다():
    h = Harness(at(TUE, 11, 0), enabled=("telegram_web",))
    assert await go("r1100", h) == 0
    assert h.ran == ["telegram_web", "register", "classify"]


async def test_범위는_켰는데_키가_없으면_설정_오류로_센다():
    h = Harness(at(TUE, 9, 0), missing_keys=("dart_api_key",))
    assert await go("r0900", h) == 1
    assert "dart" not in h.ran
    assert "DART_API_KEY" in h.text
    assert "telegram_web" in h.ran  # 다른 단계는 계속한다


async def test_한_단계가_실패해도_다음_단계는_계속한다():
    h = Harness(at(TUE, 9, 0), codes={"dart": 1})
    assert await go("r0900", h) == 1
    assert h.ran[-1] == "classify"
    assert "종료 코드 1" in h.text


async def test_시간이_넘으면_중단하고_다음으로_간다():
    h = Harness(at(TUE, 9, 0), durations={"dart": 10_000})
    assert await go("r0900", h) == 1
    assert h.timeouts["dart"] == 300  # 단계별 제한 시간
    assert "timeout" in h.text
    assert h.ran[-1] == "classify"


async def test_범위_파일을_못_읽으면_멈춘다():
    h = Harness(at(TUE, 9, 0), scope_error="수집 범위 파일이 없다")
    assert await go("r0900", h) == 1
    assert h.ran == []


# ---------------------------------------------------------------- 겹침·시각 어긋남

async def test_다른_회차가_돌고_있으면_건너뛴다():
    h = Harness(at(TUE, 9, 0), lock_free=False)
    assert await go("r0900", h) == 1
    assert h.ran == []
    assert "lock" in h.text


async def test_예정_시각과_크게_어긋나면_멈춘다():
    h = Harness(at(TUE, 18, 0))  # 9시 회차를 18시에 부름: cron 시간대를 잘못 적은 경우
    assert await go("r0900", h) == 1
    assert h.ran == []
    assert "어긋남" in h.text

    forced = Harness(at(TUE, 18, 0))
    assert await go("r0900", forced, force=True) == 0
    assert forced.ran[0] == "dart"


async def test_몇_분_늦은_건_괜찮다():
    h = Harness(at(TUE, 9, 7))
    assert await go("r0900", h) == 0
    assert h.ran[0] == "dart"


# ---------------------------------------------------------------- 장 마감 맞춤 (15:25)

async def test_15시25분은_DART가_가장_먼저():
    h = Harness(at(TUE, 15, 25))
    assert await go("r1525", h) == 0
    assert h.ran[0] == "dart"
    assert h.ran.index("telegram_pdf") > h.ran.index("news:삼성전자")  # 오래 걸리는 PDF 는 수집의 끝
    assert h.slept == []  # 평소엔 기다리지 않는다


async def test_15시25분보다_일찍_불리면_그때까지_기다린다():
    h = Harness(at(TUE, 15, 20))
    assert await go("r1525", h) == 0
    assert h.slept == [300.0]
    assert h.t >= at(TUE, 15, 25)


async def test_수능일은_마감_16시30분_5분_전까지_기다린다():
    h = Harness(at(SUNEUNG, 15, 25), close=time(16, 30))
    assert await go("r1525", h) == 0
    assert h.slept == [3600.0]  # 15:25 → 16:25
    assert h.ran[0] == "dart"
    assert h.t >= at(SUNEUNG, 16, 25)


async def test_마감_직전_시한이_지나면_남은_수집은_건너뛰고_분류는_한다():
    # 15:25 시작, 시한은 15:29:30(270초 뒤). DART 가 250초 걸리면 다음 단계에 20초만 남는다.
    h = Harness(at(TUE, 15, 25), durations={"dart": 250, "telegram_web": 100})
    assert await go("r1525", h) == 1  # telegram_web 이 20초 제한에 걸려 시간 초과
    assert h.timeouts["dart"] == 270  # 시한이 단계 제한(300초)보다 짧다
    assert h.timeouts["telegram_web"] == pytest.approx(20)
    assert "news:삼성전자" not in h.ran and "telegram_pdf" not in h.ran  # 시한 뒤라 시작하지 않음
    assert "skipped_deadline" in h.text
    assert h.ran[-2:] == ["register", "classify"]  # 분류는 시한과 상관없이 돈다


async def test_너무_오래_기다려야_하면_멈춘다():
    h = Harness(at(TUE, 15, 25), close=time(20, 0))  # 마감 20:00 이면 19:55 까지 4시간 반
    assert await go("r1525", h) == 1
    assert h.ran == []
    assert h.slept == []


async def test_기다리지_않는_옵션():
    h = Harness(at(TUE, 15, 20))
    assert await go("r1525", h, wait=False) == 0
    assert h.slept == []
    assert h.ran[0] == "dart"


# ---------------------------------------------------------------- dry-run

async def test_dry_run은_아무것도_실행하지_않는다():
    h = Harness(at(TUE, 9, 0), enabled=("dart", "telegram_web"))
    assert await go("r0900", h, dry_run=True) == 0
    assert h.ran == [] and h.slept == []
    assert "dry-run" in h.text
    assert "수집 범위에서 꺼져 있음(naver_research)" in h.text


async def test_dry_run은_휴장일도_알려준다():
    h = Harness(at(TUE, 9, 0), open_day=False)
    assert await go("r0900", h, dry_run=True) == 0
    assert "휴장일" in h.text


# ---------------------------------------------------------------- cron 파일·진짜 실행기

def test_crontab_파일이_회차표와_같다():
    """회차표의 시각을 고치고 cron 파일을 안 고치면(또는 반대) 서버에서 다른 시각에 돈다."""
    path = Path(__file__).resolve().parents[1] / "schedule" / "crontab"
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s+.*round (r\d{4})( |$)", line)
        if m:
            found[m.group(3)] = f"{m.group(1)} {m.group(2)}"
    assert found == {name: _cron_utc(rnd) for name, rnd in ROUNDS.items()}


async def test_진짜_실행기는_종료_코드를_돌려준다():
    execute = real_env(dry_run=True).execute
    assert await execute(Step("ok", ("-c", "pass")), 30) == 0
    assert await execute(Step("bad", ("-c", "import sys; sys.exit(3)")), 30) == 3


async def test_진짜_실행기는_시간이_넘으면_프로세스를_죽인다():
    execute = real_env(dry_run=True).execute
    began = clock.monotonic()
    assert await execute(Step("slow", ("-c", "import time; time.sleep(60)")), 1) is None
    assert clock.monotonic() - began < 15  # 60초를 기다리지 않는다
