"""종목 변동 요인 보고서 일괄 생성 — 보고서 대상 종목 전부를 한 번에 만들어 DB 에 적재한다.

    uv run python -m app.collectors.stock_analysis_batch --mode close --load        평일 16:00 (대상일 = 오늘)
    uv run python -m app.collectors.stock_analysis_batch --mode morning --load      평일 08:30 (대상일 = 직전 거래일)
    uv run python -m app.collectors.stock_analysis_batch --mode close --codes 005930 --dry-run   한 종목, 입력만 만든다

이 파일은 **이미 있는 두 부분을 이어 붙일 뿐**이다. 종목마다 `classified_input.load_input` 으로 입력을 만들고,
그 입력들을 한 폴더에 모아 `stock_analysis.run`(러너)에 한 번 넘긴다. 입력의 근거 범위·중복 묶기·경계 규칙은 어댑터가,
생성·검증·적재는 러너가 한다. 여기서 정하는 것은 아래 네 가지뿐이다.

## 1. 기준 시각과 대상일 — 어댑터 문서(classified_input.py 「대상일」)가 정한 규칙 그대로

    close   cutoff = 오늘 16:00 KST, target_date = 오늘
    morning cutoff = 오늘 08:30 KST, target_date = 오늘의 직전 거래일 (adapter.previous_close, market_calendar)

보고서는 대상일 D 의 16:00 과 D+1 08:30 에 두 번 만들고 두 번 모두 target_date 를 D 로 준다. 08:30 에 D 를 주어야 러너가
그 cutoff 를 D 장 마감 이후로 보고 KRX 비교를 켠다. cutoff 는 실제 실행 시각이 아니라 위의 정각이다 — 같은 정각이면 같은
근거 범위를 읽고, 러너 run_id·파일 이름의 HHMM 도 1600·0830 으로 고정된다.

평일 휴장일인지는 부르는 쪽(app.schedule)이 먼저 거른다. 여기서도 휴장일 다음 날이면 직전 거래일을 달력으로 찾는다.

## 2. 입력 등락률(change_pct) — 서버 DB 의 stock_quote_snapshot.change

러너 입력의 change_pct 는 필수 숫자("기준 시각의 등락률")이고, 장 마감 이후 KRX 가 ok 일 때만 러너가 KRX 등락률로 덮어쓴다
(stock_analysis_io.md 「기준 시각과 입력 등락률」). KRX 는 T+1 이라 16:00 에는 no_data 여서 **16:00 보고서는 이 입력값이
그대로 쓰인다**. 어댑터는 이 값을 호출하는 쪽이 넘기게 해 두었으므로(--change-pct), 서버에서는 backend 수집기가 1분 주기로
채우는 stock_quote_snapshot.change(KIS prdy_ctrt, 전일 대비 %, 부호 있음, 종목당 1행)를 쓴다.

**그 시세가 장 마감 값일 때만 쓴다.** backend 수집기는 장외에는 마감 뒤 한 번만 받으므로(quote_freshness), 마감 뒤에 받은
값이 종가 등락률이다. 그래서 `장 마감 ≤ collected_at ≤ 장 마감 + QUOTE_WINDOW` 인 시세만 인정한다. 시세가 없거나 이 범위 밖이면
(수집기가 멈췄거나 마감 뒤에 받지 못했다) **그 종목은 만들지 않고 건너뛴다.** 틀린 등락률로 원인을 설명하는 보고서가
"원인 미확인" 보고서보다 해롭다고 어댑터·#124 가 정한 원칙(누수보다 누락)과 같다. 건너뛴 종목은 사유와 함께 출력하고
종료 코드 1 로 알린다.
QUOTE_WINDOW 는 시험으로 정한 값이 아니라 가정이다. 마감 직후 한 번 받는다는 backend 동작에서 넉넉히 잡았다.

## 3. 장 마감이 16:00 뒤로 늦춰지는 날(LATE_CLOSE, 수능일 등)의 16:00 회차는 만들지 않는다

그날 16:00 은 장 마감 전이라 러너가 KRX 비교를 끄고(market_compare_skipped BEFORE_CLOSE) 입력 change_pct 를 "기준 시각의
등락률"(장중 값)로 읽는다. 장중 값을 이 일괄 생성이 정할 근거가 없어(종가가 아니다) 만들지 않고 종료 코드 0 으로 알린다.
그날 보고서는 다음 거래일 08:30 회차가 만든다. 생성 시각을 늦출지는 보고서 담당이 정할 일이다.

## 4. 한 종목의 실패는 그 종목만 건너뛴다

러너는 입력 하나라도 형식이 틀리면 한 건도 호출하지 않고 멈춘다(load_inputs). 그래서 입력을 만드는 단계에서 종목별로
실패를 걸러 러너에는 만들어진 입력만 넘긴다. 단 target_date·cutoff 가 서로 맞지 않는 오류(InputRangeError)는 종목 하나의
문제가 아니라 실행 전체의 문제라 멈춘다.

## 5. 묶음으로 나눠 돌린다 — 중간에 죽어도 앞 묶음은 남는다

러너는 한 번의 실행을 **마지막에 한 트랜잭션**으로 적재한다(stock_analysis.run). 30종목을 한 번에 넘기면 120분 제한에 걸리거나
컨테이너가 죽을 때 **이미 쓴 LLM 비용까지 전부 사라진다.** 그래서 CHUNK_SIZE 종목씩 묶어 러너를 여러 번 부른다. 묶음마다 따로
적재되므로 앞 묶음은 남는다. 러너는 입력 하나라도 검사(check_input)에 걸리면 그 실행의 **한 건도 호출하지 않고 멈추므로**, 입력을
만든 직후 같은 검사를 미리 돌려 걸리는 종목만 건너뛴다. CHUNK_SIZE 는 시험으로 정한 값이 아니라 가정이다.
묶음마다 KRX 를 한 번씩 부른다(러너가 실행 하나 안에서 기준일마다 한 번만 부르므로). 호출 수가 묶음 수만큼 늘 뿐 비용은 거의 없다.

## 결과가 남는 곳

--load 를 주면 러너가 한 트랜잭션으로 stock_move_analyses 에 넣는다(검증에 떨어진 보고서는 넣지 않는다). 입력과 meta 는
`<out>/classified_inputs/<mode>-<시각>/`, 러너 실행 기록은 `<out>/<시각>-<uuid>/` 에 남는다. 서버의 일회성 컨테이너는
끝나면 이 폴더도 사라지므로 서버에서 남기려면 `--out` 을 마운트한 곳으로 준다.
LLM 호출 비용은 러너 요약 줄(완료: …)에 나온다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import stock_analysis as runner
from app.core.database import SessionLocal
from app.core.scope import KST
from app.services.stock_analysis import classified_input as adapter
from app.services.stock_analysis import stock_meta
from app.services.stock_analysis.generate import check_input
from app.services.stock_analysis.market_compare import market_close

logger = logging.getLogger(__name__)

# 보고서를 만드는 정각(KST). stock_analysis_io.md·classified_input.py 「대상일」: 대상일 D 16:00 과 D+1 08:30.
MODE_TIMES: dict[str, time] = {"morning": time(8, 30), "close": time(16, 0)}
# 입력 등락률로 쓰는 시세를 받은 시각이 장 마감 뒤 이 안이어야 한다. 시험으로 정한 값이 아닌 가정이다(맨 위 2번).
QUOTE_WINDOW = timedelta(hours=1)
# 러너를 한 번 부를 때 넘기는 종목 수(맨 위 5번). 묶음마다 따로 적재된다. 시험으로 정한 값이 아닌 가정이다.
CHUNK_SIZE = 10

QUOTES = text(
    "SELECT stock_code, change, collected_at FROM stock_quote_snapshot WHERE stock_code IN :codes"
).bindparams(bindparam("codes", expanding=True))


def cutoff_of(mode: str, today: date) -> datetime:
    """기준 시각. 실행 시각이 아니라 정각이다."""
    return datetime.combine(today, MODE_TIMES[mode], tzinfo=KST)


def target_date_of(mode: str, today: date, open_days: Mapping[date, bool] | None) -> date:
    """대상일. close 는 오늘, morning 은 오늘의 직전 거래일."""
    if mode == "close":
        return today
    return adapter.previous_close(today, open_days).date()


def close_of(day: date) -> datetime:
    """그날 장 마감 시각(KST). LATE_CLOSE 에 있는 날은 그 시각."""
    return datetime.combine(day, market_close(day), tzinfo=KST)


def quote_problem(collected_at: datetime | None, target_date: date) -> str | None:
    """이 시세를 대상일의 종가 등락률로 써도 되는가. 문제없으면 None, 있으면 사유."""
    if collected_at is None:
        return "시세 없음(stock_quote_snapshot 에 행이 없다)"
    close = close_of(target_date)
    seen = collected_at.astimezone(KST)
    if seen < close:
        return f"장 마감({close:%m-%d %H:%M}) 전에 받은 시세({seen:%m-%d %H:%M}) — 종가가 아닐 수 있다"
    if seen > close + QUOTE_WINDOW:
        return f"장 마감({close:%m-%d %H:%M}) {QUOTE_WINDOW} 넘게 뒤에 받은 시세({seen:%m-%d %H:%M})"
    return None


async def read_quotes(session: AsyncSession, codes: Sequence[str]) -> dict[str, tuple[float, datetime]]:
    """종목코드 → (등락률 %, 받은 시각). backend 표라 ai 쪽 모델이 없어 SQL 로 읽는다."""
    rows = (await session.execute(QUOTES, {"codes": list(codes)})).all()
    return {row[0]: (float(row[1]), row[2]) for row in rows}


async def generate_inputs(
    session: AsyncSession, codes: Sequence[str], *, cutoff: datetime, target_date: date, out_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    """종목마다 러너 입력을 만들어 out_dir 에 쓴다. (만든 종목, {건너뛴 종목: 사유})."""
    quotes = await read_quotes(session, codes)
    done: list[str] = []
    skipped: dict[str, str] = {}
    for code in codes:
        quote = quotes.get(code)
        problem = quote_problem(quote[1] if quote else None, target_date)
        if problem:
            skipped[code] = problem
            continue
        try:
            payload, meta = await adapter.load_input(
                session, code, cutoff=cutoff, change_pct=quote[0], target_date=target_date,
            )
        except adapter.InputRangeError:
            raise  # 대상일·기준 시각이 안 맞는 건 종목 하나의 문제가 아니다
        except Exception as exc:  # 한 종목이 실패해도 나머지는 만든다
            logger.exception("%s: 입력 생성 실패", code)
            skipped[code] = f"입력 생성 실패: {type(exc).__name__}: {str(exc)[:200]}"
            await session.rollback()  # 실패한 쿼리가 세션을 망가뜨리지 않게
            continue
        issues = check_input(payload)  # 러너가 쓰는 검사. 하나라도 걸리면 러너는 그 실행 전체를 멈추므로 미리 거른다
        if issues:
            skipped[code] = "러너 입력 검사 실패: " + "; ".join(issues)[:200]
            continue
        adapter.write(out_dir, payload, meta)
        done.append(code)
    return done, skipped


def chunked(codes: Sequence[str], size: int) -> list[list[str]]:
    return [list(codes[i:i + size]) for i in range(0, len(codes), size)]


def input_name(code: str, out_dir: Path) -> Path:
    """어댑터가 만든 입력 파일(`<코드>-<대상일>-<HHMM>.json`). out_dir 바로 아래에 종목마다 하나다."""
    (path,) = sorted(out_dir.glob(f"{code}-*.json"))
    return path


def _label(code: str) -> str:
    return f"{code} {stock_meta.name(code) or ''}".rstrip()


async def run_batch(
    mode: str, *, now: datetime, out_root: Path, codes: Sequence[str], load: bool, dry_run: bool,
    concurrency: int, chunk_size: int = CHUNK_SIZE,
) -> int:
    """종료 코드: 0 정상(또는 늦춰진 마감일 건너뜀), 1 건너뛴 종목이 있거나 러너 오류·입력 없음."""
    today = now.astimezone(KST).date()
    cutoff = cutoff_of(mode, today)
    if mode == "close" and cutoff < close_of(today):
        print(f"{today} 은 장 마감이 {close_of(today):%H:%M} 으로 늦춰진 날이라 {cutoff:%H:%M} 회차는 만들지 않는다"
              "(맨 위 3번). 보고서는 다음 거래일 08:30 회차가 만든다")
        return 0

    async with SessionLocal() as session:
        open_days = await adapter.read_open_days(session, today)
        target_date = target_date_of(mode, today, open_days)
        basis = "market_calendar" if open_days is not None else "평일 규칙(달력 없음)"
        print(f"[{mode}] 기준 시각 {cutoff:%Y-%m-%d %H:%M} · 대상일 {target_date} (직전 거래일 판단: {basis})"
              f" · 종목 {len(codes)}개")
        out_dir = out_root / "classified_inputs" / f"{mode}-{now.astimezone(KST):%Y%m%d-%H%M%S}"
        out_dir.mkdir(parents=True, exist_ok=True)
        done, skipped = await generate_inputs(
            session, codes, cutoff=cutoff, target_date=target_date, out_dir=out_dir,
        )

    print(f"입력 {len(done)}건 만듦 · 건너뜀 {len(skipped)}건 → {out_dir}")
    for code, reason in skipped.items():
        print(f"  건너뜀 {_label(code)}: {reason}")
    if not done:
        print("만들 입력이 하나도 없어 멈춘다")
        return 1
    if dry_run:
        print("dry-run: 보고서는 만들지 않았다(LLM 호출 없음)")
        return 1 if skipped else 0
    problems = bool(skipped)
    groups = chunked(done, chunk_size)
    for number, group in enumerate(groups, 1):
        # 러너는 폴더 바로 아래 *.json 을 모두 입력으로 읽는다. 묶음마다 폴더를 따로 만들어 그 묶음의 입력만 둔다
        group_dir = out_dir / f"run-{number:02d}"
        group_dir.mkdir()
        for code in group:
            shutil.copy2(input_name(code, out_dir), group_dir)
        print(f"묶음 {number}/{len(groups)}: {len(group)}종목 생성 시작")
        try:
            result = await runner.run(group_dir, out_root=out_root, concurrency=concurrency, load=load)
        except (ValueError, RuntimeError) as exc:  # 입력 검사 실패·LLM 키 없음. 같은 원인이 다음 묶음에도 있으니 멈춘다
            print(exc)
            print(f"묶음 {number} 에서 멈춤. 앞 묶음 {number - 1}개의 결과는 적재돼 있다")
            return 1
        problems |= bool(result["errors"])
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="종목 변동 요인 보고서 일괄 생성(대상 종목 전부)")
    parser.add_argument("--mode", required=True, choices=sorted(MODE_TIMES),
                        help="close: 오늘 16:00 (대상일 오늘) / morning: 오늘 08:30 (대상일 직전 거래일)")
    parser.add_argument("--codes", nargs="+", metavar="CODE", help="이 종목만(시험용). 기본은 보고서 대상 전부")
    parser.add_argument("--load", action="store_true", help="검증 결과와 함께 DB 에 적재(없으면 파일만 만든다)")
    parser.add_argument("--dry-run", action="store_true", help="입력만 만들고 보고서는 만들지 않는다(LLM 호출 없음)")
    parser.add_argument("--concurrency", type=int, default=runner.CONCURRENCY,
                        help=f"러너 동시 호출 수 (기본 {runner.CONCURRENCY})")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE,
                        help=f"러너를 한 번 부를 때 넘길 종목 수(묶음마다 따로 적재). 기본 {CHUNK_SIZE}")
    parser.add_argument("--out", type=Path, default=Path("runs"), help="실행 결과를 둘 부모 폴더")
    args = parser.parse_args(argv)
    if args.chunk_size < 1:
        parser.error("--chunk-size 는 1 이상이어야 한다")
    if args.dry_run and args.load:
        parser.error("--dry-run 은 보고서를 만들지 않으므로 --load 와 같이 줄 수 없다")
    if args.concurrency < 1:
        parser.error("--concurrency 는 1 이상이어야 한다")
    codes = tuple(args.codes) if args.codes else stock_meta.codes()
    unknown = [c for c in codes if stock_meta.name(c) is None]
    if unknown:
        parser.error(f"stock_meta.json 에 없는 종목: {', '.join(unknown)}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def go() -> int:
        from app.core.database import engine

        try:
            return await run_batch(
                args.mode, now=datetime.now(KST), out_root=args.out, codes=codes, load=args.load,
                dry_run=args.dry_run, concurrency=args.concurrency, chunk_size=args.chunk_size,
            )
        except adapter.InputRangeError as exc:
            print(f"대상일·기준 시각이 맞지 않는다: {exc}")
            return 1
        finally:
            await engine.dispose()

    return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())
