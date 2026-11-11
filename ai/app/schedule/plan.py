"""회차표: 언제(KST) 무엇을 어떤 순서로 돌리는지.

시각은 PR #119 댓글(swimny·hakyeoung, 2026-11-10)에서 정한 값이다.

    평일   09:00  DART · 네이버 리서치 · 텔레그램(메시지·PDF) · 네이버 뉴스 → 분류
           11:00  DART · 텔레그램 · 뉴스 → 분류
           13:00  DART · 텔레그램 · 뉴스 → 분류
           15:20  네이버 리서치만 (작성일만 있는 리포트가 09:00 뒤에 올라온 것을 당일 보고서에 넣으려고)
           15:25  DART 가 가장 먼저 → 텔레그램 · 뉴스 → 분류. 장 마감(15:30) 전에 끝나야 한다
           18:00  DART · 텔레그램 · 뉴스 → 분류
    주말   18:00  텔레그램 · 뉴스 → 분류   (DART·리서치는 평일만)

보고서(평일만): 08:30(대상일 = 직전 거래일)·16:00(대상일 = 오늘). hakyeoung 이 PR #119 에서 "보고서 생성은 08:30, 16:00" 이라고
했고 어댑터 문서(classified_input.py 「대상일」)가 같은 두 시각을 쓴다. 대상 종목 전부를 한 번에 만드는 명령은
app.collectors.stock_analysis_batch 다. 보고서 회차는 수집 회차와 **다른 잠금**을 써서 오래 걸려도 수집을 막지 않고,
시작 전에 돌고 있는 수집·분류가 끝나기를 기다린다(runner.py).

휴장일(평일이어도)은 통째로 건너뛴다. 주말 18:00 회차만 휴장 여부와 상관없이 돈다.

왜 15:25 인가: DART 목록은 접수일만 주고 접수 시각을 주지 않아, 수집기가 처음 본 시각을 공개 시각으로 쓴다.
장 마감 뒤에 처음 보면 장중 공시도 다음 거래일 보고서로 넘어간다(PR #124). 그래서 마지막 장중 수집은
장 마감 직전이어야 한다. 장 마감이 늦춰지는 날(수능일 등)은 market_compare.market_close 를 따라
그날 마감 5분 전으로 미룬다(runner.py).

회차 안의 순서: 수집은 DART 를 가장 먼저(가장 빠르고 시각이 중요), 오래 걸리는 텔레그램 PDF 를 수집의 맨 끝에 둔다.
마감 시한이 있는 회차는 시한이 지나면 남은 수집 단계를 건너뛴다. 분류는 시한과 상관없이 마지막에 돈다.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import time

WEEKDAY, WEEKEND = "weekday", "weekend"

# 리서치는 작성일만 있고 주말·휴일에 쓴 글은 다음 거래일에 수집되므로 사흘 전부터 훑는다.
# 이미 받은 건 건너뛰므로(증분 수집) 겹쳐도 같은 결과다.
RESEARCH_DAYS = 3
# 텔레그램 PDF 는 건당 평균 3.7MB 라 짧게 잡는다. 이미 받은 건 건너뛴다.
TELEGRAM_PDF_DAYS = 2

MINUTE = 60


@dataclass(frozen=True)
class Step:
    name: str  # 로그에 보이는 이름
    argv: tuple[str, ...]  # python 뒤에 오는 인자
    source: str | None = None  # collection_scope.toml 출처. 꺼져 있으면 건너뛴다. None 이면 범위와 무관
    needs: tuple[str, ...] = ()  # 있어야 하는 설정(.env). 없으면 실패로 센다(범위는 켰는데 키가 없는 설정 오류)
    timeout: int = 20 * MINUTE  # 이 단계에 줄 최대 시간(초)
    collect: bool = True  # 수집 단계인가. 마감 시한은 수집 단계에만 적용한다
    any_scope: bool = False  # True 면 켜진 출처가 하나라도 있을 때만 돈다(출처가 전부 꺼진 채 분류 비용만 쓰지 않게)


def _py(module: str, *args: str) -> tuple[str, ...]:
    return ("-m", module, *args)


DART = Step("dart", _py("app.collectors.disclosure"), "dart", ("dart_api_key",), 5 * MINUTE)
RESEARCH = Step(
    "research", _py("app.collectors.analyst_report", "--days", str(RESEARCH_DAYS)),
    "naver_research", (), 10 * MINUTE,
)
CHANNELS = Step(
    "telegram_web", _py("app.collectors.news_channels"), "telegram_web", (), 15 * MINUTE,
)
TELEGRAM_PDF = Step(
    "telegram_pdf", _py("app.collectors.telegram", "--days", str(TELEGRAM_PDF_DAYS)),
    "telegram_client", ("telegram_api_id", "telegram_api_hash", "telegram_session"), 20 * MINUTE,
)
# 카드 등록은 수집기가 끝에 한 번 하지만 실패해도 원문은 남는다. 몇 번 돌려도 같은 결과라 안전망으로 둔다.
REGISTER = Step(
    "register", _py("app.collectors.sources", "register"), None, (), 5 * MINUTE,
    collect=False, any_scope=True,
)
# 분류 비용은 .env 의 CLASSIFICATION_DAILY_BUDGET·PER_STOCK_CAP 이 막는다. 상한에 닿으면 멈추고
# 남은 자료는 다음 실행이 이어서 한다. same-event 묶기는 시험 전이라 자동으로 돌리지 않는다.
CLASSIFY = Step(
    "classify", _py("app.services.classification", "run"), None, (), 40 * MINUTE,
    collect=False, any_scope=True,
)


# 보고서 일괄 생성. 30종목을 러너 동시 호출 2건으로 만들고 한 트랜잭션으로 적재한다. 한 건이 길고(추론 모델,
# 정상 호출도 3분 가까이) 시간 초과로 죽으면 적재 전이라 전부 사라지므로 넉넉히 둔다. **실제로 재 본 값이 아니다.**
# 첫 실행의 소요 시간을 보고 정한다. 켜진 출처가 없으면 입력이 비어 정형 보고서만 쌓이므로 돌지 않는다.
REPORT_TIMEOUT = 120 * MINUTE


def report_step(mode: str) -> Step:
    return Step(
        f"report:{mode}", _py("app.collectors.stock_analysis_batch", "--mode", mode, "--load"),
        None, (), REPORT_TIMEOUT, collect=False, any_scope=True,
    )


def news_steps(queries: Sequence[str]) -> list[Step]:
    """네이버 뉴스는 검색어(종목명)마다 한 번씩. 검색어는 collection_scope.toml 의 naver_news.queries 다."""
    return [
        Step(f"news:{query}", _py("app.collectors.news", query), "naver_news",
             ("naver_client_id", "naver_client_secret"), 5 * MINUTE)
        for query in queries
    ]


Plan = Callable[[str, Sequence[str]], list[Step]]


def _research_only(kind: str, queries: Sequence[str]) -> list[Step]:
    return [RESEARCH]


def _morning(kind: str, queries: Sequence[str]) -> list[Step]:
    return [DART, RESEARCH, CHANNELS, *news_steps(queries), TELEGRAM_PDF, REGISTER, CLASSIFY]


def _intraday(kind: str, queries: Sequence[str]) -> list[Step]:
    return [DART, CHANNELS, *news_steps(queries), TELEGRAM_PDF, REGISTER, CLASSIFY]


def _evening(kind: str, queries: Sequence[str]) -> list[Step]:
    if kind == WEEKEND:  # 주말은 DART·리서치가 없다
        return [CHANNELS, *news_steps(queries), TELEGRAM_PDF, REGISTER, CLASSIFY]
    return _intraday(kind, queries)


def _report_morning(kind: str, queries: Sequence[str]) -> list[Step]:
    return [report_step("morning")]


def _report_close(kind: str, queries: Sequence[str]) -> list[Step]:
    return [report_step("close")]


COLLECT, REPORT = "collect", "report"  # 회차가 쓰는 잠금 이름


@dataclass(frozen=True)
class Round:
    name: str
    at: time  # 한국 시간. cron 시각과 맞는지 대조하는 값이다
    days: tuple[str, ...]  # 이 회차가 도는 날 종류
    plan: Plan
    align_to_close: bool = False  # True 면 그날 장 마감 5분 전까지 기다렸다 시작하고, 마감 직전을 시한으로 둔다
    lock: str = COLLECT  # 보고서 회차는 다른 잠금을 쓰고, 시작 전에 수집·분류가 끝나기를 기다린다


ROUNDS: dict[str, Round] = {
    r.name: r
    for r in (
        Round("r0830", time(8, 30), (WEEKDAY,), _report_morning, lock=REPORT),
        Round("r0900", time(9, 0), (WEEKDAY,), _morning),
        Round("r1100", time(11, 0), (WEEKDAY,), _intraday),
        Round("r1300", time(13, 0), (WEEKDAY,), _intraday),
        Round("r1520", time(15, 20), (WEEKDAY,), _research_only),
        Round("r1525", time(15, 25), (WEEKDAY,), _intraday, align_to_close=True),
        Round("r1600", time(16, 0), (WEEKDAY,), _report_close, lock=REPORT),
        Round("r1800", time(18, 0), (WEEKDAY, WEEKEND), _evening),
    )
}


def python_argv(step: Step) -> list[str]:
    return [sys.executable, *step.argv]
