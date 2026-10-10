"""터미널에서 소스별 검색 결과를 눈으로 확인한다.

    uv run python -m app.services.news 삼성전자
    uv run python -m app.services.news 삼성전자 --display 50 --json
    uv run python -m app.services.news 삼성전자 --body        # 원문 본문까지 추출
"""

import argparse
import asyncio
import json

from app.services.news import naver
from app.services.news.content import attach_bodies


def _fmt(item) -> str:
    ts = item.published_at.strftime("%m-%d %H:%M")
    line = f"[{ts}] {item.publisher:<22} {item.title}"
    if item.raw_text is not None:
        line += f"  (원문 {len(item.raw_text)}자 → 정제 {len(item.cleaned_text or '')}자)"
    elif item.body_error:
        line += f"  (본문 실패: {item.body_error})"
    return line


async def _run(args: argparse.Namespace) -> None:
    items = await naver.search(args.query, display=args.display)
    if args.body:
        items = await attach_bodies(items)
    if args.json:
        print(json.dumps([i.model_dump(mode="json") for i in items], ensure_ascii=False, indent=2))
        return
    for item in items:
        print(_fmt(item))
    print(f"\n{len(items)}건", end="")
    if args.body:
        ok = sum(1 for i in items if i.raw_text)
        print(f" / 본문 성공 {ok}건", end="")
    print()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--display", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.add_argument("--body", action="store_true", help="원문 본문 추출")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
