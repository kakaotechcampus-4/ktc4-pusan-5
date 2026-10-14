"""공통 자료 ID(source_card) 등록·조회와 보관 정책에 따른 본문 삭제.

    uv run python -m app.collectors.sources register        # 카드가 없는 원문에 공통 자료 ID 를 만든다
    uv run python -m app.collectors.sources show 12 34      # 공통 ID 로 출처·시각·본문 유무를 본다
    uv run python -m app.collectors.sources show 12 --body  # 본문 앞부분까지 (--full 이면 전체)
    uv run python -m app.collectors.sources purge --ids 12 34 --reason "정책 이름"            # 대상만 센다
    uv run python -m app.collectors.sources purge --kind news --before 2026-11-01 --reason "..." --confirm

register 는 **몇 번을 돌려도 결과가 같다.** 이미 카드가 있는 원문은 고르지 않고, 원문 하나에
카드 하나라는 고유 제약이 있다. 수집기도 끝날 때 같은 등록을 부르므로, 이 명령은 처음 넘겨받은
기존 뉴스·PDF 를 등록하거나 수집기의 등록이 실패했을 때 쓴다.

이관 전 news 행의 canonical_url(중복 판정용 주소)도 여기서 채운다. 이미 다른 행이 같은 주소를
가지고 있으면 비워 두고 목록을 보여준다. 같은 기사가 두 행으로 들어가 있던 것이다 — 합치지
않으니 사람이 확인한다.

show 는 원문 본문을 기본으로 출력하지 않는다. 원문은 팀 내부의 분류·검증에만 쓴다.
--body·--full 로 본 내용을 공개된 곳에 옮기지 않는다.

purge 는 보관 정책이 정해진 뒤 사람이 실행한다(repositories/retention.py). 본문만 지우고 행·id·
출처 정보는 남긴다. 되돌릴 수 없으므로 --confirm 이 없으면 대상 수만 보여준다.
"""

import argparse
import asyncio
from datetime import date, datetime, time

from app.core.database import SessionLocal
from app.core.scope import KST
from app.repositories.retention import KINDS, purge, purge_targets
from app.repositories.source_card import (
    SourceRecord,
    backfill_canonical_urls,
    get_sources,
    register_missing_sources,
)

PREVIEW_CHARS = 200


async def register() -> tuple[dict[str, int], list[tuple[int, str]]]:
    """(종류별 새 카드 수, canonical_url 을 채우지 못한 news 행)."""
    async with SessionLocal() as session:
        backfill = await backfill_canonical_urls(session)
        await session.commit()
    async with SessionLocal() as session:
        cards = await register_missing_sources(session)
        await session.commit()
    return cards, backfill.collisions


async def show(card_ids: list[int], *, include_body: bool) -> list[SourceRecord]:
    async with SessionLocal() as session:
        return await get_sources(session, card_ids, include_body=include_body)


async def run_purge(
    *, card_ids: list[int] | None, kind: str | None, before: date | None, reason: str,
    confirm: bool,
) -> tuple[dict[str, int], bool]:
    """(종류별 수, 실제로 지웠는가). confirm 이 아니면 세기만 한다."""
    collected_before = datetime.combine(before, time.min, KST) if before else None
    async with SessionLocal() as session:
        targets = await purge_targets(session, card_ids=card_ids, kind=kind,
                                      collected_before=collected_before)
        if not confirm:
            return targets.counts(), False
        done = await purge(session, targets, reason=reason)
        await session.commit()
    return done, True


def record_lines(record: SourceRecord, *, full: bool) -> list[str]:
    when = record.published_at.isoformat() if record.published_at else (
        record.write_date.isoformat() if record.write_date else "시각 모름")
    lines = [
        f"[{record.id}] {record.kind} #{record.raw_id} · {record.collection_path}"
        f" · 발행처 {record.publisher or '모름'}" + (f" · 채널 {record.channel}" if record.channel else ""),
        f"    {record.title or '(제목 없음)'}",
        f"    {record.url or '(주소 없음)'} · {when}",
        "    본문 " + ("있음" if record.has_body else f"없음 — {record.body_missing_reason}")
        + (f" · 받은 시각 {record.body_fetched_at.isoformat()}" if record.body_fetched_at else ""),
    ]
    if record.forwarded_from_url:
        lines.append(f"    전달된 글: 원글 {record.forwarded_from_url}")
    if record.edit_detected_at or record.edited:
        lines.append(f"    수정 표시 {record.edited} · 본문 변경 감지 {record.edit_detected_at}")
    if record.body:
        body = record.body if full else record.body.replace("\n", " ")[:PREVIEW_CHARS]
        lines.append(f"    {body}")
    for found in record.discoveries:
        lines.append(
            f"    ↳ {found.kind} {found.status} · {found.message_url}"
            + (f" · {found.discovered_url}" if found.discovered_url else "")
            + (f" → {found.final_url}" if found.final_url and found.final_url != found.discovered_url
               else "")
        )
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description="공통 자료 ID 등록·조회와 보관 정책에 따른 본문 삭제")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("register", help="카드가 없는 원문에 공통 자료 ID 를 만든다")
    show_parser = sub.add_parser("show", help="공통 자료 ID 로 출처·시각·본문 유무를 본다")
    show_parser.add_argument("ids", type=int, nargs="+")
    show_parser.add_argument("--body", action="store_true", help="본문 앞부분도 출력한다 (내부 확인용)")
    show_parser.add_argument("--full", action="store_true", help="본문 전체를 출력한다 (내부 확인용)")
    purge_parser = sub.add_parser("purge", help="보관 정책에 따라 본문을 지운다. 행·id·출처는 남긴다")
    target = purge_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--ids", type=int, nargs="+", help="지울 공통 자료 ID")
    target.add_argument("--kind", choices=KINDS, help="이 종류에서 --before 이전에 수집한 것 전부")
    purge_parser.add_argument("--before", type=date.fromisoformat,
                              help="--kind 와 함께. 이 날짜(KST 0시) 전에 수집한 것")
    purge_parser.add_argument("--reason", required=True, help="어느 보관 정책에 따른 삭제인지")
    purge_parser.add_argument("--confirm", action="store_true",
                              help="실제로 지운다. 없으면 대상 수만 센다. 되돌릴 수 없다")
    args = p.parse_args()

    if args.command == "register":
        cards, collisions = asyncio.run(register())
        print("공통 자료 ID 새로 " + " · ".join(f"{k} {n}" for k, n in cards.items()))
        if collisions:
            print(f"canonical_url 을 채우지 못한 news {len(collisions)}건 — 같은 주소의 행이 이미 있다:")
            for news_id, key in collisions:
                print(f"  news #{news_id} {key}")
        return

    if args.command == "purge":
        if args.kind and not args.before:
            p.error("--kind 에는 --before 가 필요하다")
        counts, done = asyncio.run(run_purge(
            card_ids=args.ids, kind=args.kind, before=args.before, reason=args.reason,
            confirm=args.confirm,
        ))
        summary = " · ".join(f"{k} {n}" for k, n in counts.items())
        print(f"본문을 지웠다: {summary}" if done else
              f"지울 대상: {summary}\n  실제로 지우려면 --confirm 을 붙인다. 되돌릴 수 없다.")
        return

    records = asyncio.run(show(args.ids, include_body=args.body or args.full))
    for record in records:
        print("\n".join(record_lines(record, full=args.full)))
    missing = sorted(set(args.ids) - {r.id for r in records})
    if missing:
        p.exit(1, f"원문을 찾지 못한 공통 자료 ID: {', '.join(map(str, missing))}\n")


if __name__ == "__main__":
    main()
