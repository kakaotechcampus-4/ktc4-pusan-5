"""종목코드·기준일 목록의 시장 맥락을 JSON 파일로 남긴다. 실험용이다. DB 를 쓰지 않는다.

    uv run python -m app.services.market_data --codes 005930,000660 --dates 2026-10-27,2026-10-24
    uv run python -m app.services.market_data --codes 105560 --dates 20261027 --out runs/x.json

기준일마다 KRX 를 두 번(코스피 지수, 유가증권 전 종목)만 부르고 종목별 계산은 그 응답으로 한다.
기본 저장 위치는 runs/market_context/ 다(ai/.gitignore 의 runs/).
파일에는 계산 결과만 들어간다. 키·요청 주소는 남기지 않는다.
"""

import argparse
import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.market_data.context import build_market_context
from app.services.market_data.krx import fetch_kospi, fetch_stock_daily

KST = timezone(timedelta(hours=9))
DEFAULT_OUT_DIR = Path("runs/market_context")


def parse_day(text: str) -> date:
    """2026-10-27 또는 20261027."""
    digits = text.strip().replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        raise argparse.ArgumentTypeError(f"날짜 형식이 아니다: {text!r} (2026-10-27 또는 20261027)")
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))


def parse_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


async def collect(codes: list[str], days: list[date]) -> list[dict]:
    results = []
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        for day in days:
            kospi = await fetch_kospi(client, day)
            stocks = await fetch_stock_daily(client, day) if kospi is not None else []
            for code in codes:
                ctx = build_market_context(code, day, kospi, stocks)
                results.append(ctx.model_dump(mode="json"))
                print(f"{day} {code} {ctx.name or ''} {ctx.status}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="시장 맥락을 JSON 으로 남긴다")
    parser.add_argument("--codes", type=parse_list, required=True, help="종목코드, 쉼표로 구분")
    parser.add_argument("--dates", required=True, help="기준일, 쉼표로 구분 (2026-10-27 또는 20261027)")
    parser.add_argument("--out", type=Path, help=f"저장할 파일. 없으면 {DEFAULT_OUT_DIR}/<시각>.json")
    args = parser.parse_args()
    days = [parse_day(d) for d in parse_list(args.dates)]

    # httpx 의 요청 로그는 필요 없다. KRX 키는 헤더라 주소에 없지만 굳이 남기지 않는다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    results = asyncio.run(collect(args.codes, days))

    now = datetime.now(KST)
    out = args.out or DEFAULT_OUT_DIR / f"{now:%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generatedAt": now.isoformat(timespec="seconds"), "results": results}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {out} ({len(results)}건)")


if __name__ == "__main__":
    main()
