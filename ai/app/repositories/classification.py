"""자료 분류의 DB 읽기·쓰기 (CLASSIFICATION_DB_DRAFT 4·5절).

    sync_basis            기준 JSON → 기준표 4개. 산업·외부 기업은 지우지 않고 빠진 것에 retired_at 을
                          적는다(과거 결과가 FK 로 가리킨다). 연결·관계는 통째로 바꾼다
    stored_basis_versions 기준표에 들어 있는 기준 버전. 분류 전에 기준 파일과 같은지 본다
    cards_to_classify     분류할 자료(뉴스·PDF·메시지)의 공통 ID
    save_run              분류 결과 하나를 회차로 저장한다. 현재 회차 교체와 source_card_stocks 갱신을
                          같은 트랜잭션에서 한다(4-3·4-6). 커밋은 부르는 쪽이 한다
    classified_sources    종목 하나의 판정 자료 + 공통 배경(거시·시장) 자료 (5-2, 생성 쪽에 넘기는 것)

공시는 분류하지 않는다(11절 10번). 종목은 이미 dart_stock_code 로 이어져 있고 제목뿐이다.
"""

from datetime import datetime

from sqlalchemy import and_, delete, exists, func, literal, not_, null, select, union, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceCard
from app.models.classification import (
    ClassificationEvent,
    ClassificationEventApplicability,
    ClassificationEventEntity,
    ClassificationRun,
    CompanyRelation,
    ExternalCompany,
    Industry,
    StockIndustry,
)
from app.repositories.source_card import (
    available_since,
    available_within,
    body_observed_by,
    get_sources,
    replace_stock_tags,
)
from app.services.classification.basis import Basis
from app.services.classification.pipeline import ClassificationResult

CLASSIFIABLE_CARD_TYPES = ("news", "pdf", "message")
TAGGED_BY = "classification"
DEFAULT_LABELS = ("DIRECT", "INDIRECT_CONTEXT")
# 자료 대표값(card_label)을 고르는 순서. 생성 쪽 mention(옛 이름 match)은 이 값이 아니라 사건의 path 로 정한다
LABEL_STRENGTH = ("DIRECT", "INDIRECT_CONTEXT", "UNKNOWN", "NOT_APPLICABLE")


# ── 기준표 ────────────────────────────────────────────────────────────────

async def sync_basis(session: AsyncSession, basis: Basis) -> dict[str, int]:
    version = basis.version
    # 상위 산업을 먼저 넣는다(parent_code FK)
    for industry in sorted(basis.industries.values(), key=lambda i: len(basis.ancestors(i.code))):
        values = {"name": industry.name, "parent_code": industry.parent,
                  "aliases": list(industry.aliases), "basis_version": version, "retired_at": None}
        await session.execute(insert(Industry).values(code=industry.code, **values)
                              .on_conflict_do_update(index_elements=["code"], set_=values))
    retired_industries = (await session.execute(
        update(Industry)
        .where(Industry.code.not_in(list(basis.industries)), Industry.retired_at.is_(None))
        .values(retired_at=func.now())
    )).rowcount

    for company in basis.externals.values():
        values = {"name": company.name, "country": company.country, "stock_code": company.stock_code,
                  "ticker": company.ticker, "basis_version": version, "retired_at": None}
        await session.execute(insert(ExternalCompany).values(code=company.code, **values)
                              .on_conflict_do_update(index_elements=["code"], set_=values))
    retired_externals = (await session.execute(
        update(ExternalCompany)
        .where(ExternalCompany.code.not_in(list(basis.externals)),
               ExternalCompany.retired_at.is_(None))
        .values(retired_at=func.now())
    )).rowcount

    await session.execute(delete(StockIndustry))
    await session.execute(insert(StockIndustry).values([{
        "stock_code": link.stock_code, "industry_code": link.industry_code,
        "exposure": link.exposure, "via_company": link.via_company,
        "via_stock_code": link.via_stock_code, "stage": link.stage,
        "supply_role": link.supply_role, "source": link.source,
        "source_as_of": link.source_as_of, "note": link.note, "basis_version": version,
    } for link in basis.stock_industries]))

    await session.execute(delete(CompanyRelation))

    def ends(code: str) -> tuple[str | None, str | None]:
        return (code, None) if code in basis.stocks else (None, code)

    rows = []
    for relation in basis.relations:
        from_stock, from_external = ends(relation.from_code)
        to_stock, to_external = ends(relation.to_code)
        rows.append({
            "from_stock_code": from_stock, "from_external_code": from_external,
            "to_stock_code": to_stock, "to_external_code": to_external,
            "relation_type": relation.relation_type, "industry_code": relation.industry_code,
            "source": relation.source, "note": relation.note, "basis_version": version,
        })
    await session.execute(insert(CompanyRelation).values(rows))

    return {"industries": len(basis.industries), "retired_industries": retired_industries,
            "external_companies": len(basis.externals), "retired_externals": retired_externals,
            "stock_industries": len(basis.stock_industries),
            "company_relations": len(basis.relations)}


async def stored_basis_versions(session: AsyncSession) -> set[str]:
    query = union(
        select(Industry.basis_version).where(Industry.retired_at.is_(None)),
        select(ExternalCompany.basis_version).where(ExternalCompany.retired_at.is_(None)),
        select(StockIndustry.basis_version),
        select(CompanyRelation.basis_version),
    )
    return set((await session.execute(query)).scalars().all())


# ── 분류할 자료 ───────────────────────────────────────────────────────────

async def cards_to_classify(
    session: AsyncSession, *, card_ids: list[int] | None = None, since: datetime | None = None,
    limit: int | None = None, retry: bool = False,
) -> list[int]:
    """분류할 공통 ID. 최근 자료부터.

    card_ids 를 주면 회차가 있어도 고른다(재분류). 안 주면 회차가 없는 자료만, retry 면 현재 회차가 없는
    자료(실패·본문 없음·건너뜀만 있는 자료)도 고른다.
    """
    query = select(SourceCard.id).where(SourceCard.card_type.in_(CLASSIFIABLE_CARD_TYPES))
    if card_ids is not None:
        query = query.where(SourceCard.id.in_(card_ids))
    else:
        runs = select(ClassificationRun.id).where(ClassificationRun.source_card_id == SourceCard.id)
        if retry:
            runs = runs.where(ClassificationRun.is_current)
        query = query.where(not_(exists(runs)))
    if since is not None:
        query = query.where(available_since(since))
    query = query.order_by(SourceCard.available_at.desc().nulls_last(), SourceCard.id.desc())
    if limit is not None:
        query = query.limit(limit)
    return list((await session.execute(query)).scalars().all())


async def classifiable_card_ids(session: AsyncSession, *, since: datetime | None = None) -> list[int]:
    """회차 유무와 상관없는 분류 대상 전체의 공통 ID. 묶기 측정처럼 자료 전체를 봐야 할 때 쓴다."""
    query = select(SourceCard.id).where(SourceCard.card_type.in_(CLASSIFIABLE_CARD_TYPES))
    if since is not None:
        query = query.where(available_since(since))
    return list((await session.execute(query.order_by(SourceCard.id))).scalars().all())


# ── 회차 저장 ─────────────────────────────────────────────────────────────

async def save_run(session: AsyncSession, card_id: int, result: ClassificationResult, *,
                   make_current: bool = True) -> int:
    """결과 하나를 회차로 저장하고 회차 id 를 돌려준다.

    make_current = False 면 저장만 하고 조회에 쓰는 회차는 바꾸지 않는다(모델 비교 실험용).
    성공(ok)한 회차만 현재 회차가 될 수 있다. 실패한 회차는 응답 원문과 오류만 남긴다.
    """
    # 같은 자료를 동시에 분류해도 현재 회차가 둘이 되지 않게 카드 행을 잠근다
    await session.execute(select(SourceCard.id).where(SourceCard.id == card_id).with_for_update())
    current = make_current and result.status == "ok"
    if current:
        await session.execute(
            update(ClassificationRun)
            .where(ClassificationRun.source_card_id == card_id, ClassificationRun.is_current)
            .values(is_current=False)
        )

    extract, link, judge = (result.calls.get(step) for step in ("extract", "link", "judge"))
    usage = result.usage
    if link is not None:
        usage["link"]["raw_response"] = link.raw_response
    run = ClassificationRun(
        source_card_id=card_id, status=result.status,
        model=extract.model if extract else None,
        prompt_sha256=extract.prompt_sha256 if extract else None,
        criteria_version=result.criteria_version if extract else None,
        basis_version=result.basis_version, splitter_version=result.splitter_version,
        input_sha256=result.input_sha256, sentence_count=result.sentence_count,
        raw_response=extract.raw_response if extract else None,
        judge_prompt_sha256=judge.prompt_sha256 if judge else None,
        judge_raw_response=judge.raw_response if judge else None,
        judge_fixes=result.judge_fixes if judge else {}, error=result.error, usage=usage,
        is_current=current,
    )
    session.add(run)
    await session.flush()
    if result.status != "ok":
        return run.id

    events = []
    for item in result.events:
        event = item.event
        row = ClassificationEvent(
            run_id=run.id, order_index=event.order_index, scope=event.scope, role=event.role,
            tense=event.tense, sentence_indices=list(event.sentence_indices),
            context_indices=list(event.context_indices), mentions=list(event.mentions),
            reason=event.reason,
        )
        session.add(row)
        events.append((row, item))
    await session.flush()

    for row, item in events:
        session.add_all(ClassificationEventEntity(
            event_id=row.id, stock_code=link.stock_code, industry_code=link.industry_code,
            external_code=link.external_code, mention=link.mention, linked_by=link.linked_by,
            via_subsidiary=link.via_subsidiary,
        ) for link in item.links)
        judgments = {j.stock_code: j for j in item.judgments}
        session.add_all(ClassificationEventApplicability(
            event_id=row.id, stock_code=c.stock_code, label=judgments[c.stock_code].label,
            path=c.path, industry_code=c.industry_code, via_stock_code=c.via_stock_code,
            via_external_code=c.via_external_code, relation_type=c.relation_type,
            relation_refs=c.relation_refs, direct_allowed=c.direct_allowed,
            reason=judgments[c.stock_code].reason,
        ) for c in item.candidates)
    await session.flush()

    if current:
        # 이 자료의 분류 색인만 바꾼다. 리포트·공시가 정한 종목(다른 tagged_by)은 건드리지 않는다
        await replace_stock_tags(session, card_id, TAGGED_BY, sorted(result.direct_stocks()))
    return run.id


# ── 종목별 조회 (5-2) ──────────────────────────────────────────────────────

async def classified_sources(
    session: AsyncSession, stock_code: str, *, until: datetime, since: datetime | None = None,
    labels: tuple[str, ...] = DEFAULT_LABELS,
) -> dict:
    """종목 하나에 붙는 분류 자료. 반환 형태는 CLASSIFICATION_DB_DRAFT 5-2 와 같다(키는 snake_case).

        판정       현재 회차 사건의 판정 중 이 종목·판정 조건에 맞는 것
        공통 배경  현재 회차 사건 중 scope 가 macro·market 인 것 (모든 종목에 붙는다)

    DIRECT 가 아닌 판정과 공통 배경은 원인으로 확정한 것이 아니다(전제 P4·P5). 원문은 넣지 않는다 —
    source_card_id 로 get_sources 를 부른다.

    사건은 본문에서 나왔다. 공개는 until 전이어도 본문을 그 뒤에 받았거나 받은 시각을 모르면 그 시점에는
    알 수 없던 내용이라 sources 에서 빼고 not_observed 로 센다(get_sources 의 cutoff 와 같은 규칙).
    """
    window = available_within(until, since)
    base = (
        select(SourceCard.id.label("card_id"), ClassificationEvent.id.label("event_id"))
        .join(ClassificationRun, ClassificationRun.source_card_id == SourceCard.id)
        .join(ClassificationEvent, ClassificationEvent.run_id == ClassificationRun.id)
        .where(ClassificationRun.is_current, window)
    )
    judged = (
        base.add_columns(ClassificationEventApplicability.label,
                         ClassificationEventApplicability.path)
        .join(ClassificationEventApplicability,
              ClassificationEventApplicability.event_id == ClassificationEvent.id)
        .where(ClassificationEventApplicability.stock_code == stock_code,
               ClassificationEventApplicability.label.in_(labels))
    )
    common = (
        base.add_columns(null().label("label"), ClassificationEvent.scope.label("path"))
        .where(ClassificationEvent.scope.in_(("macro", "market")))
    )
    hits = (await session.execute(union(judged, common))).all()
    picked = {(row.card_id, row.event_id): (row.label, row.path) for row in hits}
    events = {e.id: e for e in (await session.execute(
        select(ClassificationEvent).where(ClassificationEvent.id.in_({e for _, e in picked}))
    )).scalars()} if picked else {}
    run_ids = {e.id: e.run_id for e in events.values()}

    # 오래된 순서. stock_card_ids 와 같은 정렬이다
    channels = dict((await session.execute(
        select(SourceCard.id, SourceCard.channel_id)
        .where(SourceCard.id.in_({card for card, _ in picked}))
        .order_by(SourceCard.event_date, SourceCard.available_at.nulls_first(), SourceCard.id)
    )).all()) if picked else {}
    card_ids = list(channels)
    records = {r.id: r for r in await get_sources(session, card_ids)}

    sources = []
    not_observed = 0
    for card_id in card_ids:
        record = records.get(card_id)
        if record is None:
            continue
        if not body_observed_by(record, until):
            not_observed += 1
            continue
        items = sorted(((events[event_id], label, path) for (card, event_id), (label, path)
                        in picked.items() if card == card_id), key=lambda x: x[0].order_index)
        found = [label for _, label, _ in items if label]
        sources.append({
            "source_card_id": card_id, "card_type": record.kind, "source_name": record.publisher,
            "url": record.url, "channel_id": channels[card_id],
            "available_at": record.available_at.isoformat() if record.available_at else None,
            "body_status": record.body_status,
            "card_label": min(found, key=LABEL_STRENGTH.index) if found else None,
            "events": [{
                "event_id": event.id, "run_id": run_ids[event.id], "scope": event.scope,
                "role": event.role, "tense": event.tense,
                "sentence_indices": list(event.sentence_indices),
                "context_indices": list(event.context_indices), "label": label, "path": path,
            } for event, label, path in items],
        })

    unclassified, failed = await _missing_counts(session, window)
    return {"sources": sources, "unclassified": unclassified, "failed": failed,
            "not_observed": not_observed}


async def _missing_counts(session: AsyncSession, window) -> tuple[int, int]:
    """기간 안의 분류 대상 자료 중 (회차가 없는 수, 마지막 회차가 실패인 수). 본문 없음·건너뜀은 세지 않는다."""
    any_run = exists().where(ClassificationRun.source_card_id == SourceCard.id)
    current = exists().where(ClassificationRun.source_card_id == SourceCard.id,
                             ClassificationRun.is_current)
    last_status = (
        select(ClassificationRun.status)
        .where(ClassificationRun.source_card_id == SourceCard.id)
        .order_by(ClassificationRun.id.desc()).limit(1).scalar_subquery()
    )
    row = (await session.execute(
        select(
            func.count().filter(not_(any_run)),
            func.count().filter(and_(not_(current), last_status == literal("failed"))),
        ).select_from(SourceCard)
        .where(SourceCard.card_type.in_(CLASSIFIABLE_CARD_TYPES), window)
    )).one()
    return row[0], row[1]
