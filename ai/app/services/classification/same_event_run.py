"""`same-event` 명령. 판단은 same_event.py, 저장은 repositories/classification_same_event.py 다.

자료 하나마다 다시 읽는다. 앞 자료에서 만든 묶음이 다음 자료의 후보가 돼야 한다.

--dry-run 은 저장할 때와 같은 길로 돌리고 끝에 전부 되돌린다. 그래서 LLM 비용은 그대로 든다.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.scope import KST
from app.llm.client import endpoint, format_cost
from app.repositories.classification_same_event import (
    cards_to_cluster,
    cluster_counts,
    events_to_cluster,
    representatives_near,
    save_clustering,
)
from app.repositories.source_card import get_sources
from app.services.classification.same_event import assign_clusters, candidates_for


@dataclass
class SameEventSummary:
    sources: int = 0
    calls: int = 0
    failures: int = 0  # 호출 실패·응답 깨짐·문장 복원 실패. 다음 실행에서 다시 본다
    cost: float = 0.0
    fixes: Counter = field(default_factory=Counter)
    clusters: set[int] = field(default_factory=set)  # 이번에 사건이 들어간 묶음
    counts: dict[int, dict] = field(default_factory=dict)  # 그 묶음의 지금까지 수


async def cluster_sources(session: AsyncSession, *, since: datetime | None = None,
                          limit: int | None = None, dry_run: bool = False,
                          report: Callable[[str], None] = print) -> SameEventSummary:
    summary = SameEventSummary()
    card_ids = await cards_to_cluster(session, since=since, limit=limit)
    for n, card_id in enumerate(card_ids, start=1):
        events = await events_to_cluster(session, card_id)
        if not events:  # 고른 뒤에 재분류돼 대상 사건이 없어졌다
            continue
        representatives =await representatives_near(session, events[0].available_at)
        candidates = candidates_for(events, representatives)
        wanted = {representatives[c].card_id for clusters in candidates.values() for c in clusters}
        records = (await get_sources(session, [card_id, *wanted], include_body=True)
                   if wanted else [])
        if not dry_run:
            await session.commit()  # LLM 을 기다리는 동안 트랜잭션을 열어 두지 않는다

        clustering = await assign_clusters(events, candidates, representatives,
                                           {r.id: r.body for r in records})
        touched = await save_clustering(session, events, clustering)
        if not dry_run:
            await session.commit()

        summary.sources += 1
        summary.clusters |= touched
        summary.fixes.update(clustering.fixes)
        cost = 0.0
        if clustering.call is not None:
            cost = clustering.call.usage_record()["cost"]
            summary.calls += 1
            summary.cost += cost
        if clustering.error:
            summary.failures += 1
        report(f"[{n:>3}/{len(card_ids)}] 자료 {card_id:<7} 사건 {len(events):>2} → "
               f"묶음 {sorted(touched)}  남김 {len(events) - len(clustering.clusters)}  "
               f"{'호출' if clustering.call else '호출 안 함'} {format_cost(cost)}")
        if clustering.error:
            report(f"        오류 {clustering.error[:200]}")
    # 되돌리기 전에 센다. --dry-run 의 묶음은 이 세션에서만 보인다
    summary.counts = await cluster_counts(session, summary.clusters, until=datetime.now(KST))
    if dry_run:
        await session.rollback()
    return summary


async def run_same_event(since: date | None, limit: int | None, dry_run: bool) -> None:
    try:
        endpoint()  # 키가 없으면 자료를 읽기 전에 멈춘다
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    start = datetime.combine(since, time(), KST) if since else None
    if dry_run:
        print("저장하지 않는다. LLM 비용은 든다.")
    async with SessionLocal() as session:
        summary = await cluster_sources(session, since=start, limit=limit, dry_run=dry_run)
    fixes = {key: value for key, value in summary.fixes.items() if value}
    print()
    for cluster_id, count in sorted(summary.counts.items(),
                                    key=lambda item: (-item[1]["source_count"], item[0])):
        print(f"묶음 {cluster_id:<7} 자료 {count['source_count']:>3} · 출처 {count['publisher_count']:>3}"
              f" · {count['counts_by_type']}")
    print(f"\n자료 {summary.sources} · 묶음 {len(summary.clusters)} · 호출 {summary.calls}"
          f" · 실패 {summary.failures} · 비용 {format_cost(summary.cost)}"
          + (f" · 보정 {fixes}" if fixes else ""))
