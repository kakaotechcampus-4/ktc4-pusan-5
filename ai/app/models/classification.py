"""자료 분류 표 8개. 설계는 docs/CLASSIFICATION_DB_DRAFT.md 4절이다.

**기준표 4개 — 사람이 만든 기준 JSON 에서 넣는다(services/classification/basis.py).**

    industries            산업 하나 (계층)
    stock_industries      (종목, 산업) 연결 하나. 경로·단계가 판정 상한(direct_allowed)을 정한다
    external_companies    30종목 밖 기업. 관계의 출발점으로만 쓰고 후보가 되지 않는다
    company_relations     (기업 → 기업, 관계 종류, 산업) 하나. 한쪽 끝은 30종목

**결과표 4개 — 자료가 들어올 때마다 LLM 이 쌓는다.**

    classification_runs                 자료 1건을 1번 분류한 기록 (재분류하면 행이 는다)
    classification_events               그 회차의 사건 하나
    classification_event_entities       사건의 표기 하나 → 종목·산업·외부 기업
    classification_event_applicability  (사건, 후보 종목) 판정 하나

**같은 사건 묶음 3개 — 분류를 마친 뒤 별도 명령이 쌓는다(docs/CLASSIFICATION_SAME_EVENT.md).**

    classification_event_clusters         묶음 하나. 대표 사건은 바뀌지 않는다
    classification_event_cluster_members  사건의 소속. 사건 하나는 묶음 하나에만 든다
    classification_cluster_calls          묶기 LLM 호출 기록. 부르지 않은 자료는 행이 없다

기준표는 **지금 기준만** 담는다. 기준이 바뀌면 통째로 바꾸고, 예전 기준은 버전별 JSON 파일로 남는다.
그래서 결과표는 관계 행을 FK 로 가리키지 않고, 판정 당시 넘긴 관계를 relation_refs 에 복사한다.

company_relations 는 10-29 멘토링 방향대로 코드 경로가 달라지는 값(양 끝·종류·산업)만 칸으로 두고,
제품 범위·단계·근거 수준·실제 당사자·기간은 note 에 적는다. note 는 판정 입력에 그대로 넘어간다.

종목코드는 BE stock 표를 FK 로 걸지 않는다(source_card_stocks 와 같은 관례).
배열 칼럼 CHECK 에 `IS TRUE` 를 붙이는 이유는 4-4 에 있다 — `{2,NULL}` 의 `0 < ALL(...)` 는 NULL 이라
CHECK 를 통과한다.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

RUN_STATUSES = ("ok", "failed", "no_body", "skipped")
SCOPES = ("company", "industry", "macro", "market")
ROLES = ("cause", "price_move", "outlook", "context", "analyst_view")
TENSES = ("past", "future")
LABELS = ("DIRECT", "INDIRECT_CONTEXT", "NOT_APPLICABLE", "UNKNOWN")
PATHS = ("company", "industry", "relation")
CLUSTER_CALL_STATUSES = ("ok", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class Industry(Base):
    __tablename__ = "industries"
    __table_args__ = (
        CheckConstraint("parent_code IS NULL OR parent_code <> code", name="ck_industries_parent"),
        CheckConstraint("jsonb_typeof(aliases) = 'array'", name="ck_industries_aliases"),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_code: Mapped[str | None] = mapped_column(String(32), ForeignKey("industries.code"))
    # 조회어. 동의어가 아니다 — 산업보다 좁은 제품명("HBM")도 들어간다
    aliases: Mapped[list] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    # 기준에서 빠진 시각. 과거 분류 결과가 FK 로 가리키므로 지우지 않는다
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalCompany(Base):
    __tablename__ = "external_companies"
    __table_args__ = (
        # 종목코드(숫자·영문 대문자)와 겹치지 않게 소문자로 시작한다. company_relations 의 고유 식 인덱스가 이걸 전제로 한다
        CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="ck_external_companies_code"),
        CheckConstraint("stock_code IS NULL OR stock_code ~ '^[0-9A-Z]{6}$'",
                        name="ck_external_companies_stock_code"),
        Index("uq_external_companies_stock_code", "stock_code", unique=True,
              postgresql_where=sql_text("stock_code IS NOT NULL")),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    stock_code: Mapped[str | None] = mapped_column(String(6))  # 국내 상장사면
    ticker: Mapped[str | None] = mapped_column(String(16))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockIndustry(Base):
    __tablename__ = "stock_industries"
    __table_args__ = (
        UniqueConstraint("stock_code", "industry_code", name="uq_stock_industries"),
        CheckConstraint(_in("exposure", ("own", "subsidiary", "stake")),
                        name="ck_stock_industries_exposure"),
        CheckConstraint(_in("stage", ("operating", "planned")), name="ck_stock_industries_stage"),
        CheckConstraint("(exposure = 'own') = (via_company IS NULL)",
                        name="ck_stock_industries_via_company"),
        CheckConstraint("(exposure = 'stake') = (via_stock_code IS NOT NULL)",
                        name="ck_stock_industries_via_stock"),
        CheckConstraint("via_stock_code IS NULL OR via_stock_code <> stock_code",
                        name="ck_stock_industries_not_self"),
        CheckConstraint("source <> '' AND (via_company IS NULL OR via_company <> '')",
                        name="ck_stock_industries_text"),
        Index("ix_stock_industries_industry_code", "industry_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    industry_code: Mapped[str] = mapped_column(String(32), ForeignKey("industries.code"))
    # own: 직접 영위 | subsidiary: 비상장 자회사가 영위 | stake: 상장사를 거친 지분 노출
    exposure: Mapped[str] = mapped_column(String(16))
    via_company: Mapped[str | None] = mapped_column(Text)
    via_stock_code: Mapped[str | None] = mapped_column(String(6))  # stake 일 때만. 30종목 밖이어도 된다
    stage: Mapped[str] = mapped_column(String(16))  # operating | planned
    supply_role: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    source_as_of: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    basis_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyRelation(Base):
    __tablename__ = "company_relations"
    __table_args__ = (
        CheckConstraint("num_nonnulls(from_stock_code, from_external_code) = 1",
                        name="ck_company_relations_from"),
        CheckConstraint("num_nonnulls(to_stock_code, to_external_code) = 1",
                        name="ck_company_relations_to"),
        # 외부 기업끼리의 관계는 넣지 않는다. 후보는 30종목뿐이고 1-hop 이라 쓰일 데가 없다
        CheckConstraint("from_stock_code IS NOT NULL OR to_stock_code IS NOT NULL",
                        name="ck_company_relations_has_stock"),
        CheckConstraint("from_stock_code IS NULL OR to_stock_code IS NULL"
                        " OR from_stock_code <> to_stock_code", name="ck_company_relations_not_self"),
        CheckConstraint(_in("relation_type", ("supplier", "competitor", "ownership")),
                        name="ck_company_relations_type"),
        # 방향이 없는 경쟁 관계는 한 행만. 종목끼리는 코드가 작은 쪽, 외부 기업과는 종목 쪽이 from
        CheckConstraint("relation_type <> 'competitor' OR (from_stock_code IS NOT NULL"
                        " AND (to_external_code IS NOT NULL OR from_stock_code < to_stock_code))",
                        name="ck_company_relations_competitor_order"),
        CheckConstraint("source <> ''", name="ck_company_relations_source"),
        Index("ix_company_relations_from_stock_code", "from_stock_code"),
        Index("ix_company_relations_to_stock_code", "to_stock_code"),
        Index("ix_company_relations_from_external_code", "from_external_code"),
        Index("ix_company_relations_to_external_code", "to_external_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_stock_code: Mapped[str | None] = mapped_column(String(6))
    from_external_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("external_companies.code"))
    to_stock_code: Mapped[str | None] = mapped_column(String(6))
    to_external_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("external_companies.code"))
    # supplier: from 이 to 의 공급사 | competitor: 서로 경쟁사 | ownership: from 이 to 의 지분을 가짐
    relation_type: Mapped[str] = mapped_column(String(16))
    industry_code: Mapped[str | None] = mapped_column(String(32), ForeignKey("industries.code"))
    source: Mapped[str] = mapped_column(Text)
    # 제품 범위·단계·근거 수준·실제 당사자·기간 (10-29). 판정 입력에 그대로 넘긴다
    note: Mapped[str | None] = mapped_column(Text)
    basis_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# NULL 이 섞인 칼럼에 그냥 UNIQUE 를 걸면 NULL 끼리 다른 값으로 봐서 중복을 못 막는다. 종목코드와
# 외부 기업 코드는 겹치지 않으므로(ck_external_companies_code) 합쳐서 비교해도 된다.
Index(
    "uq_company_relations_key",
    func.coalesce(CompanyRelation.from_stock_code, CompanyRelation.from_external_code),
    func.coalesce(CompanyRelation.to_stock_code, CompanyRelation.to_external_code),
    CompanyRelation.relation_type,
    func.coalesce(CompanyRelation.industry_code, sql_text("''")),
    unique=True,
)


class ClassificationRun(Base):
    __tablename__ = "classification_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_classification_runs_status"),
        # 실패한 회차는 조회에 쓸 수 없다
        CheckConstraint("NOT is_current OR status = 'ok'", name="ck_classification_runs_current"),
        # 성공한 회차는 문장 번호를 다시 풀 수 있어야 한다
        CheckConstraint("status <> 'ok' OR (splitter_version IS NOT NULL"
                        " AND input_sha256 IS NOT NULL AND sentence_count IS NOT NULL)",
                        name="ck_classification_runs_replayable"),
        Index("ix_classification_runs_source_card_id", "source_card_id"),
        # 자료마다 지금 쓰는 회차는 하나
        Index("uq_classification_runs_current", "source_card_id", unique=True,
              postgresql_where=sql_text("is_current")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # CASCADE 아님 — 자료를 지우려 하면 막힌다. 돈 들여 만든 분류 기록이 조용히 사라지지 않게
    source_card_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("source_card.id"))
    status: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))  # ① 추출 모델. 단계별 모델은 usage 에
    prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    criteria_version: Mapped[str | None] = mapped_column(String(32))
    basis_version: Mapped[str] = mapped_column(String(64))
    splitter_version: Mapped[str | None] = mapped_column(String(32))
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    sentence_count: Mapped[int | None] = mapped_column(Integer)
    raw_response: Mapped[str | None] = mapped_column(Text)
    judge_prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    judge_raw_response: Mapped[str | None] = mapped_column(Text)
    judge_fixes: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    # 단계(extract·link·judge)별 토큰·비용·모델. ② 코드 선택의 응답 원문도 link.raw_response 에 남긴다
    # ③ 홍보성 Jev 를 켰으면 promo 칸에 사건별 확률·오류·원화 비용이 함께 남는다(promo.py)
    usage: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class ClassificationEvent(Base):
    __tablename__ = "classification_events"
    __table_args__ = (
        UniqueConstraint("run_id", "order_index", name="uq_classification_events_order"),
        CheckConstraint(_in("scope", SCOPES), name="ck_classification_events_scope"),
        CheckConstraint(_in("role", ROLES), name="ck_classification_events_role"),
        CheckConstraint(_in("tense", TENSES), name="ck_classification_events_tense"),
        CheckConstraint("cardinality(sentence_indices) > 0 AND (0 < ALL(sentence_indices)) IS TRUE"
                        " AND array_ndims(sentence_indices) = 1",
                        name="ck_classification_events_sentences"),
        CheckConstraint("(0 < ALL(context_indices)) IS TRUE"
                        " AND coalesce(array_ndims(context_indices), 1) = 1",
                        name="ck_classification_events_context"),
        CheckConstraint("('' <> ALL(mentions)) IS TRUE AND coalesce(array_ndims(mentions), 1) = 1",
                        name="ck_classification_events_mentions"),
        Index("ix_classification_events_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classification_runs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(16))
    # past | future. 10-21 실험에서 happened·expected 일 때 모델이 role 칸에 이 값을 넣는 실수를 해서 바꿨다
    tense: Mapped[str] = mapped_column(String(16))
    sentence_indices: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    context_indices: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=sql_text("'{}'::integer[]"))
    mentions: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    reason: Mapped[str | None] = mapped_column(Text)


class ClassificationEventEntity(Base):
    __tablename__ = "classification_event_entities"
    __table_args__ = (
        CheckConstraint("num_nonnulls(stock_code, industry_code, external_code) = 1",
                        name="ck_classification_event_entities_target"),
        CheckConstraint("industry_code IS NULL OR via_subsidiary IS NULL",
                        name="ck_classification_event_entities_industry_sub"),
        CheckConstraint("mention <> '' AND (via_subsidiary IS NULL OR via_subsidiary <> '')",
                        name="ck_classification_event_entities_text"),
        CheckConstraint(_in("linked_by", ("alias", "llm_code")),
                        name="ck_classification_event_entities_linked_by"),
        # 표기가 다르면 같은 대상이라도 행이 따로 생긴다. 사건의 mentions 와 비교할 때 미연결로 잘못 보지 않게
        UniqueConstraint("event_id", "stock_code", "mention",
                         name="uq_classification_event_entities_stock"),
        UniqueConstraint("event_id", "industry_code", "mention",
                         name="uq_classification_event_entities_industry"),
        UniqueConstraint("event_id", "external_code", "mention",
                         name="uq_classification_event_entities_external"),
        Index("ix_classification_event_entities_event_id", "event_id"),
        Index("ix_classification_event_entities_stock_code", "stock_code"),
        Index("ix_classification_event_entities_industry_code", "industry_code"),
        Index("ix_classification_event_entities_external_code", "external_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classification_events.id", ondelete="CASCADE"))
    stock_code: Mapped[str | None] = mapped_column(String(6))
    industry_code: Mapped[str | None] = mapped_column(String(32), ForeignKey("industries.code"))
    external_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("external_companies.code"))
    mention: Mapped[str] = mapped_column(Text)
    linked_by: Mapped[str] = mapped_column(String(16))  # alias | llm_code
    via_subsidiary: Mapped[str | None] = mapped_column(Text)


class ClassificationEventApplicability(Base):
    __tablename__ = "classification_event_applicability"
    __table_args__ = (
        # 한 사건·종목에 판정 하나. 여러 경로로 후보가 됐으면 위쪽 경로 하나가 대표다
        UniqueConstraint("event_id", "stock_code", name="uq_classification_event_applicability"),
        CheckConstraint(_in("label", LABELS), name="ck_classification_event_applicability_label"),
        CheckConstraint(_in("path", PATHS), name="ck_classification_event_applicability_path"),
        CheckConstraint("relation_type IS NULL OR "
                        + _in("relation_type", ("supplier", "competitor", "ownership")),
                        name="ck_classification_event_applicability_relation_type"),
        CheckConstraint("(path = 'industry') = (industry_code IS NOT NULL)",
                        name="ck_classification_event_applicability_industry"),
        CheckConstraint("(path = 'relation') = (num_nonnulls(via_stock_code, via_external_code) = 1"
                        " AND relation_type IS NOT NULL)",
                        name="ck_classification_event_applicability_relation"),
        CheckConstraint("path = 'relation'"
                        " OR num_nonnulls(via_stock_code, via_external_code, relation_type) = 0",
                        name="ck_classification_event_applicability_no_via"),
        CheckConstraint("jsonb_typeof(relation_refs) = 'array'"
                        " AND (path <> 'relation' OR jsonb_array_length(relation_refs) > 0)",
                        name="ck_classification_event_applicability_refs"),
        # 관계로 들어온 종목은 기사가 말하지 않은 종목이라 DIRECT 가 될 수 없다
        CheckConstraint("path <> 'relation' OR NOT direct_allowed",
                        name="ck_classification_event_applicability_relation_cap"),
        CheckConstraint("path <> 'company' OR direct_allowed",
                        name="ck_classification_event_applicability_company_cap"),
        CheckConstraint("direct_allowed OR label <> 'DIRECT'",
                        name="ck_classification_event_applicability_direct"),
        Index("ix_classification_event_applicability_event_id", "event_id"),
        Index("ix_classification_event_applicability_stock_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classification_events.id", ondelete="CASCADE"))
    stock_code: Mapped[str] = mapped_column(String(6))
    label: Mapped[str] = mapped_column(String(24))
    path: Mapped[str] = mapped_column(String(16))
    industry_code: Mapped[str | None] = mapped_column(String(32), ForeignKey("industries.code"))
    via_stock_code: Mapped[str | None] = mapped_column(String(6))
    via_external_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("external_companies.code"))
    relation_type: Mapped[str | None] = mapped_column(String(16))
    # 이 후보에 걸린 관계 전부. 대표 경로와 상관없이 보존한다
    relation_refs: Mapped[list] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    direct_allowed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)


class ClassificationEventCluster(Base):
    __tablename__ = "classification_event_clusters"
    __table_args__ = (
        UniqueConstraint("representative_event_id",
                         name="uq_classification_event_clusters_representative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 묶음을 처음 만든 사건. 재분류로 옛 회차가 돼도 바꾸지 않는다
    representative_event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classification_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassificationClusterCall(Base):
    __tablename__ = "classification_cluster_calls"
    __table_args__ = (
        CheckConstraint(_in("status", CLUSTER_CALL_STATUSES),
                        name="ck_classification_cluster_calls_status"),
        Index("ix_classification_cluster_calls_source_card_id", "source_card_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_card_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("source_card.id"))
    status: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    raw_response: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    # 응답 검사에서 고친 건수(후보 밖 번호 등)
    fixes: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassificationEventClusterMember(Base):
    __tablename__ = "classification_event_cluster_members"
    __table_args__ = (
        Index("ix_classification_event_cluster_members_cluster_id", "cluster_id"),
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classification_events.id"), primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classification_event_clusters.id"))
    # LLM 에 보내지 않고 새 묶음을 만든 사건은 비어 있다
    call_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("classification_cluster_calls.id"))
