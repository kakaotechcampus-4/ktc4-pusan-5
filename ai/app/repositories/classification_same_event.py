"""같은 사건 묶기의 DB 읽기·쓰기 (docs/CLASSIFICATION_SAME_EVENT.md 4·5절).

    cards_to_cluster      아직 묶지 않은 대상 사건이 있는 자료. 공개 시각이 빠른 것부터
    events_to_cluster     자료 하나의 아직 묶지 않은 대상 사건
    representatives_near  공개 시각이 가까운 묶음의 대표 사건. 재분류로 옛 회차가 된 대표도 넣는다
    save_clustering       호출 기록과 소속을 저장한다. 커밋은 부르는 쪽이 한다
    cluster_counts        묶음의 자료 수·출처 수·종류별 수. 저장하지 않고 조회할 때 센다
    event_clusters        사건마다 묶음 번호와 위의 수. classified_sources 가 쓴다

대상은 현재 회차의 company·industry 사건이다. 공개 시각이 없는 자료는 후보를 시간으로 좁힐 수 없어 뺀다.

**수는 기준 시각으로 잘라 센다.** 그 시점에 없던 자료가 수에 들어가면 안 된다. 현재 회차의 사건만, 공개와 본문
수집이 모두 기준 시각 전인 자료만 센다(classified_sources 와 같은 규칙).
"""

from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceCard
from app.models.classification import (
    ClassificationClusterCall,
    ClassificationEvent,
    ClassificationEventCluster,
    ClassificationEventClusterMember,
    ClassificationEventEntity,
    ClassificationRun,
)
from app.repositories.source_card import (
    SourceRecord,
    available_within,
    body_observed_by,
    get_sources,
)
from app.services.classification.link import TARGET_SCOPES
from app.services.classification.same_event import (
    CANDIDATE_WINDOW,
    ClusterEvent,
    Clustering,
    entity_code,
    unlinked_mentions,
)


def _event_rows():
    """사건과 그 회차·자료 정보."""
    return (
        select(ClassificationEvent, ClassificationRun.splitter_version,
               ClassificationRun.input_sha256, SourceCard.id.label("card_id"),
               SourceCard.available_at)
        .join(ClassificationRun, ClassificationRun.id == ClassificationEvent.run_id)
        .join(SourceCard, SourceCard.id == ClassificationRun.source_card_id)
    )


def _unclustered_targets(query):
    return (
        query.outerjoin(ClassificationEventClusterMember,
                        ClassificationEventClusterMember.event_id == ClassificationEvent.id)
        .where(ClassificationRun.is_current, ClassificationEvent.scope.in_(TARGET_SCOPES),
               SourceCard.available_at.is_not(None),
               ClassificationEventClusterMember.event_id.is_(None))
    )


async def _cluster_events(session: AsyncSession, rows: list) -> list[ClusterEvent]:
    links = defaultdict(list)
    if rows:
        found = await session.execute(
            select(ClassificationEventEntity)
            .where(ClassificationEventEntity.event_id.in_([r.ClassificationEvent.id for r in rows]))
        )
        for link in found.scalars():
            links[link.event_id].append(link)
    return [ClusterEvent(
        event_id=row.ClassificationEvent.id, run_id=row.ClassificationEvent.run_id,
        card_id=row.card_id, order_index=row.ClassificationEvent.order_index,
        scope=row.ClassificationEvent.scope, available_at=row.available_at,
        codes=frozenset(entity_code(link.stock_code, link.industry_code, link.external_code)
                        for link in links[row.ClassificationEvent.id]),
        mentions=unlinked_mentions(row.ClassificationEvent.mentions,
                                   [link.mention for link in links[row.ClassificationEvent.id]]),
        sentence_indices=tuple(row.ClassificationEvent.sentence_indices),
        context_indices=tuple(row.ClassificationEvent.context_indices),
        splitter_version=row.splitter_version, input_sha256=row.input_sha256,
    ) for row in rows]


async def cards_to_cluster(session: AsyncSession, *, since: datetime | None = None,
                           limit: int | None = None) -> list[int]:
    query = _unclustered_targets(
        select(SourceCard.id, SourceCard.available_at)
        .join(ClassificationRun, ClassificationRun.source_card_id == SourceCard.id)
        .join(ClassificationEvent, ClassificationEvent.run_id == ClassificationRun.id)
    )
    if since is not None:
        query = query.where(SourceCard.available_at >= since)
    query = (query.group_by(SourceCard.id, SourceCard.available_at)
             .order_by(SourceCard.available_at, SourceCard.id))
    if limit is not None:
        query = query.limit(limit)
    return [row.id for row in (await session.execute(query)).all()]


async def events_to_cluster(session: AsyncSession, card_id: int) -> list[ClusterEvent]:
    query = (_unclustered_targets(_event_rows()).where(SourceCard.id == card_id)
             .order_by(ClassificationEvent.order_index))
    return await _cluster_events(session, (await session.execute(query)).all())


async def representatives_near(session: AsyncSession, at: datetime) -> dict[int, ClusterEvent]:
    """묶음 번호 → 대표 사건. 시간으로만 좁힌다. 나머지 후보 조건은 same_event.is_candidate 다."""
    query = (
        _event_rows()
        .add_columns(ClassificationEventCluster.id.label("cluster_id"))
        .join(ClassificationEventCluster,
              ClassificationEventCluster.representative_event_id == ClassificationEvent.id)
        .where(SourceCard.available_at.between(at - CANDIDATE_WINDOW, at + CANDIDATE_WINDOW))
        .order_by(ClassificationEventCluster.id)
    )
    rows = (await session.execute(query)).all()
    events = await _cluster_events(session, rows)
    return {row.cluster_id: event for row, event in zip(rows, events, strict=True)}


async def save_clustering(session: AsyncSession, events: list[ClusterEvent],
                          clustering: Clustering) -> set[int]:
    """호출 기록과 소속을 저장하고, 사건이 들어간 묶음 번호를 돌려준다. 부르지 않았으면 호출 행이 없다."""
    call_id = None
    if clustering.call is not None:
        row = ClassificationClusterCall(
            source_card_id=events[0].card_id, status="failed" if clustering.error else "ok",
            model=clustering.call.model, prompt_sha256=clustering.call.prompt_sha256,
            raw_response=clustering.call.raw_response, error=clustering.error,
            usage=clustering.call.usage_record(), fixes=clustering.fixes,
        )
        session.add(row)
        await session.flush()
        call_id = row.id

    touched: set[int] = set()
    for event in events:
        if event.order_index not in clustering.clusters:
            continue
        cluster_id = clustering.clusters[event.order_index]
        if cluster_id is None:
            cluster = ClassificationEventCluster(representative_event_id=event.event_id)
            session.add(cluster)
            await session.flush()
            cluster_id = cluster.id
        session.add(ClassificationEventClusterMember(
            event_id=event.event_id, cluster_id=cluster_id,
            call_id=call_id if event.order_index in clustering.asked else None,
        ))
        touched.add(cluster_id)
    await session.flush()
    return touched


async def cluster_counts(session: AsyncSession, cluster_ids: set[int], *, until: datetime,
                         since: datetime | None = None,
                         observed_by: datetime | None = None) -> dict[int, dict]:
    """묶음 번호 → source_count·publisher_count·counts_by_type.

    한 자료의 사건 둘이 같은 묶음이어도 자료는 하나다. 한 매체가 고쳐 올린 기사는 source_count 만 늘린다.
    발행처를 모르는 자료는 publisher_count 에 넣지 않는다. 같은 묶음에서 세는 자료를 링크로 공유한 메시지는
    셀 때 뺀다 — 기사 하나가 두 건으로 보이면 안 된다.

    공개는 until 까지, 본문은 observed_by 까지 받은 자료를 센다(classified_sources 와 같은 기준).
    observed_by 를 안 주면 until 이다.
    """
    if not cluster_ids:
        return {}
    rows = (await session.execute(
        select(ClassificationEventClusterMember.cluster_id, SourceCard.id)
        .join(ClassificationEvent,
              ClassificationEvent.id == ClassificationEventClusterMember.event_id)
        .join(ClassificationRun, ClassificationRun.id == ClassificationEvent.run_id)
        .join(SourceCard, SourceCard.id == ClassificationRun.source_card_id)
        .where(ClassificationEventClusterMember.cluster_id.in_(cluster_ids),
               ClassificationRun.is_current, available_within(until, since))
        .distinct()
    )).all()
    records = {r.id: r for r in await get_sources(session, list({row.id for row in rows}))}
    seen = defaultdict(list)
    for row in rows:
        record = records.get(row.id)
        if record is not None and body_observed_by(record, observed_by or until):
            seen[row.cluster_id].append(record)
    counted = {cluster_id: _without_link_shares(seen[cluster_id]) for cluster_id in cluster_ids}
    return {cluster_id: {
        "source_count": len(found),
        "publisher_count": len({r.publisher for r in found if r.publisher}),
        "counts_by_type": dict(Counter(r.kind for r in found)),
    } for cluster_id, found in counted.items()}


def _without_link_shares(records: list[SourceRecord]) -> list[SourceRecord]:
    """링크 대상이 같이 세어질 때만 뺀다. 기준 시각 전에 기사를 못 봤으면 그때는 메시지가 유일한 자료다."""
    ids = {record.id for record in records}
    return [record for record in records
            if record.kind != "message"
            or not any(found.target_card_id in ids for found in record.discoveries)]


async def event_clusters(session: AsyncSession, event_ids: set[int], *, until: datetime,
                         since: datetime | None = None,
                         observed_by: datetime | None = None) -> dict[int, dict]:
    """사건 id → 묶음 번호와 수. 묶이지 않은 사건은 결과에 없다."""
    if not event_ids:
        return {}
    clusters = dict((await session.execute(
        select(ClassificationEventClusterMember.event_id,
               ClassificationEventClusterMember.cluster_id)
        .where(ClassificationEventClusterMember.event_id.in_(event_ids))
    )).all())
    counts = await cluster_counts(session, set(clusters.values()), until=until, since=since,
                                  observed_by=observed_by)
    return {event_id: {"cluster_id": cluster_id, **counts[cluster_id]}
            for event_id, cluster_id in clusters.items()}
