"""classification tables: basis, runs, events, entities, applicability

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

자료를 종목·산업·시장으로 분류하고, 사건이 각 종목에 해당하는지 판정해 저장하는 표 8개를 만든다.
설계는 docs/CLASSIFICATION_DB_DRAFT.md 4절, 칼럼 설명은 app/models/classification.py 에 있다.

    기준표  industries · external_companies · stock_industries · company_relations
    결과표  classification_runs · classification_events · classification_event_entities ·
            classification_event_applicability

기준표는 비워 둔 채 만든다. 기준 JSON 에서 넣는 것은 앱 코드다
(`python -m app.services.classification basis`) — 리비전이 그 시점 기준에 묶이지 않게.

**downgrade 는 분류 회차가 하나라도 있으면 멈춘다(전제 P9).** 분류 결과는 다시 만들려면 LLM 비용이
들고, 원문이 보관 정책으로 지워졌으면 다시 만들 수 없다. 기준표는 JSON 에서 다시 넣으면 되므로 막지 않는다.

Revision ID: 0027_classification
Revises: 0026_source_card_disclosures
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027_classification"
down_revision: str | None = "0026_source_card_disclosures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "industries",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parent_code", sa.String(length=32), nullable=True),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("basis_version", sa.String(length=64), nullable=False),
        _created_at(),
        sa.CheckConstraint("parent_code IS NULL OR parent_code <> code", name="ck_industries_parent"),
        sa.CheckConstraint("jsonb_typeof(aliases) = 'array'", name="ck_industries_aliases"),
        sa.ForeignKeyConstraint(["parent_code"], ["industries.code"]),
        sa.PrimaryKeyConstraint("code"),
    )

    op.create_table(
        "external_companies",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("stock_code", sa.String(length=6), nullable=True),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("basis_version", sa.String(length=64), nullable=False),
        _created_at(),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="ck_external_companies_code"),
        sa.CheckConstraint("stock_code IS NULL OR stock_code ~ '^[0-9A-Z]{6}$'",
                           name="ck_external_companies_stock_code"),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("uq_external_companies_stock_code", "external_companies", ["stock_code"],
                    unique=True, postgresql_where=sa.text("stock_code IS NOT NULL"))

    op.create_table(
        "stock_industries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("industry_code", sa.String(length=32), nullable=False),
        sa.Column("exposure", sa.String(length=16), nullable=False),
        sa.Column("via_company", sa.Text(), nullable=True),
        sa.Column("via_stock_code", sa.String(length=6), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("supply_role", sa.String(length=16), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_as_of", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("basis_version", sa.String(length=64), nullable=False),
        _created_at(),
        sa.CheckConstraint(_in("exposure", ("own", "subsidiary", "stake")),
                           name="ck_stock_industries_exposure"),
        sa.CheckConstraint(_in("stage", ("operating", "planned")), name="ck_stock_industries_stage"),
        sa.CheckConstraint("(exposure = 'own') = (via_company IS NULL)",
                           name="ck_stock_industries_via_company"),
        sa.CheckConstraint("(exposure = 'stake') = (via_stock_code IS NOT NULL)",
                           name="ck_stock_industries_via_stock"),
        sa.CheckConstraint("via_stock_code IS NULL OR via_stock_code <> stock_code",
                           name="ck_stock_industries_not_self"),
        sa.CheckConstraint("source <> '' AND (via_company IS NULL OR via_company <> '')",
                           name="ck_stock_industries_text"),
        sa.ForeignKeyConstraint(["industry_code"], ["industries.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_code", "industry_code", name="uq_stock_industries"),
    )
    op.create_index("ix_stock_industries_industry_code", "stock_industries", ["industry_code"])

    op.create_table(
        "company_relations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("from_stock_code", sa.String(length=6), nullable=True),
        sa.Column("from_external_code", sa.String(length=32), nullable=True),
        sa.Column("to_stock_code", sa.String(length=6), nullable=True),
        sa.Column("to_external_code", sa.String(length=32), nullable=True),
        sa.Column("relation_type", sa.String(length=16), nullable=False),
        sa.Column("industry_code", sa.String(length=32), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("basis_version", sa.String(length=64), nullable=False),
        _created_at(),
        sa.CheckConstraint("num_nonnulls(from_stock_code, from_external_code) = 1",
                           name="ck_company_relations_from"),
        sa.CheckConstraint("num_nonnulls(to_stock_code, to_external_code) = 1",
                           name="ck_company_relations_to"),
        sa.CheckConstraint("from_stock_code IS NOT NULL OR to_stock_code IS NOT NULL",
                           name="ck_company_relations_has_stock"),
        sa.CheckConstraint("from_stock_code IS NULL OR to_stock_code IS NULL"
                           " OR from_stock_code <> to_stock_code",
                           name="ck_company_relations_not_self"),
        sa.CheckConstraint(_in("relation_type", ("supplier", "competitor", "ownership")),
                           name="ck_company_relations_type"),
        sa.CheckConstraint("relation_type <> 'competitor' OR (from_stock_code IS NOT NULL"
                           " AND (to_external_code IS NOT NULL OR from_stock_code < to_stock_code))",
                           name="ck_company_relations_competitor_order"),
        sa.CheckConstraint("source <> ''", name="ck_company_relations_source"),
        sa.ForeignKeyConstraint(["from_external_code"], ["external_companies.code"]),
        sa.ForeignKeyConstraint(["to_external_code"], ["external_companies.code"]),
        sa.ForeignKeyConstraint(["industry_code"], ["industries.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("from_stock_code", "to_stock_code", "from_external_code", "to_external_code"):
        op.create_index(f"ix_company_relations_{column}", "company_relations", [column])
    op.create_index(
        "uq_company_relations_key", "company_relations",
        [sa.text("coalesce(from_stock_code, from_external_code)"),
         sa.text("coalesce(to_stock_code, to_external_code)"),
         "relation_type",
         sa.text("coalesce(industry_code, '')")],
        unique=True,
    )

    op.create_table(
        "classification_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_card_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("criteria_version", sa.String(length=32), nullable=True),
        sa.Column("basis_version", sa.String(length=64), nullable=False),
        sa.Column("splitter_version", sa.String(length=32), nullable=True),
        sa.Column("input_sha256", sa.String(length=64), nullable=True),
        sa.Column("sentence_count", sa.Integer(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("judge_prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("judge_raw_response", sa.Text(), nullable=True),
        sa.Column("judge_fixes", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint(_in("status", ("ok", "failed", "no_body", "skipped")),
                           name="ck_classification_runs_status"),
        sa.CheckConstraint("NOT is_current OR status = 'ok'", name="ck_classification_runs_current"),
        sa.CheckConstraint("status <> 'ok' OR (splitter_version IS NOT NULL"
                           " AND input_sha256 IS NOT NULL AND sentence_count IS NOT NULL)",
                           name="ck_classification_runs_replayable"),
        sa.ForeignKeyConstraint(["source_card_id"], ["source_card.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classification_runs_source_card_id", "classification_runs",
                    ["source_card_id"])
    op.create_index("uq_classification_runs_current", "classification_runs", ["source_card_id"],
                    unique=True, postgresql_where=sa.text("is_current"))

    op.create_table(
        "classification_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("tense", sa.String(length=16), nullable=False),
        sa.Column("sentence_indices", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("context_indices", postgresql.ARRAY(sa.Integer()),
                  server_default=sa.text("'{}'::integer[]"), nullable=False),
        sa.Column("mentions", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"),
                  nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(_in("scope", ("company", "industry", "macro", "market")),
                           name="ck_classification_events_scope"),
        sa.CheckConstraint(
            _in("role", ("cause", "price_move", "outlook", "context", "analyst_view")),
            name="ck_classification_events_role"),
        sa.CheckConstraint(_in("tense", ("past", "future")), name="ck_classification_events_tense"),
        sa.CheckConstraint("cardinality(sentence_indices) > 0 AND (0 < ALL(sentence_indices)) IS TRUE"
                           " AND array_ndims(sentence_indices) = 1",
                           name="ck_classification_events_sentences"),
        sa.CheckConstraint("(0 < ALL(context_indices)) IS TRUE"
                           " AND coalesce(array_ndims(context_indices), 1) = 1",
                           name="ck_classification_events_context"),
        sa.CheckConstraint("('' <> ALL(mentions)) IS TRUE"
                           " AND coalesce(array_ndims(mentions), 1) = 1",
                           name="ck_classification_events_mentions"),
        sa.ForeignKeyConstraint(["run_id"], ["classification_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "order_index", name="uq_classification_events_order"),
    )
    op.create_index("ix_classification_events_run_id", "classification_events", ["run_id"])

    op.create_table(
        "classification_event_entities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=True),
        sa.Column("industry_code", sa.String(length=32), nullable=True),
        sa.Column("external_code", sa.String(length=32), nullable=True),
        sa.Column("mention", sa.Text(), nullable=False),
        sa.Column("linked_by", sa.String(length=16), nullable=False),
        sa.Column("via_subsidiary", sa.Text(), nullable=True),
        sa.CheckConstraint("num_nonnulls(stock_code, industry_code, external_code) = 1",
                           name="ck_classification_event_entities_target"),
        sa.CheckConstraint("industry_code IS NULL OR via_subsidiary IS NULL",
                           name="ck_classification_event_entities_industry_sub"),
        sa.CheckConstraint("mention <> '' AND (via_subsidiary IS NULL OR via_subsidiary <> '')",
                           name="ck_classification_event_entities_text"),
        sa.CheckConstraint(_in("linked_by", ("alias", "llm_code")),
                           name="ck_classification_event_entities_linked_by"),
        sa.ForeignKeyConstraint(["event_id"], ["classification_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["industry_code"], ["industries.code"]),
        sa.ForeignKeyConstraint(["external_code"], ["external_companies.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "stock_code", "mention",
                            name="uq_classification_event_entities_stock"),
        sa.UniqueConstraint("event_id", "industry_code", "mention",
                            name="uq_classification_event_entities_industry"),
        sa.UniqueConstraint("event_id", "external_code", "mention",
                            name="uq_classification_event_entities_external"),
    )
    for column in ("event_id", "stock_code", "industry_code", "external_code"):
        op.create_index(f"ix_classification_event_entities_{column}",
                        "classification_event_entities", [column])

    op.create_table(
        "classification_event_applicability",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("label", sa.String(length=24), nullable=False),
        sa.Column("path", sa.String(length=16), nullable=False),
        sa.Column("industry_code", sa.String(length=32), nullable=True),
        sa.Column("via_stock_code", sa.String(length=6), nullable=True),
        sa.Column("via_external_code", sa.String(length=32), nullable=True),
        sa.Column("relation_type", sa.String(length=16), nullable=True),
        sa.Column("relation_refs", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("direct_allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            _in("label", ("DIRECT", "INDIRECT_CONTEXT", "NOT_APPLICABLE", "UNKNOWN")),
            name="ck_classification_event_applicability_label"),
        sa.CheckConstraint(_in("path", ("company", "industry", "relation")),
                           name="ck_classification_event_applicability_path"),
        sa.CheckConstraint("relation_type IS NULL OR "
                           + _in("relation_type", ("supplier", "competitor", "ownership")),
                           name="ck_classification_event_applicability_relation_type"),
        sa.CheckConstraint("(path = 'industry') = (industry_code IS NOT NULL)",
                           name="ck_classification_event_applicability_industry"),
        sa.CheckConstraint("(path = 'relation') = (num_nonnulls(via_stock_code, via_external_code) = 1"
                           " AND relation_type IS NOT NULL)",
                           name="ck_classification_event_applicability_relation"),
        sa.CheckConstraint("path = 'relation'"
                           " OR num_nonnulls(via_stock_code, via_external_code, relation_type) = 0",
                           name="ck_classification_event_applicability_no_via"),
        sa.CheckConstraint("jsonb_typeof(relation_refs) = 'array'"
                           " AND (path <> 'relation' OR jsonb_array_length(relation_refs) > 0)",
                           name="ck_classification_event_applicability_refs"),
        sa.CheckConstraint("path <> 'relation' OR NOT direct_allowed",
                           name="ck_classification_event_applicability_relation_cap"),
        sa.CheckConstraint("path <> 'company' OR direct_allowed",
                           name="ck_classification_event_applicability_company_cap"),
        sa.CheckConstraint("direct_allowed OR label <> 'DIRECT'",
                           name="ck_classification_event_applicability_direct"),
        sa.ForeignKeyConstraint(["event_id"], ["classification_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["industry_code"], ["industries.code"]),
        sa.ForeignKeyConstraint(["via_external_code"], ["external_companies.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "stock_code", name="uq_classification_event_applicability"),
    )
    op.create_index("ix_classification_event_applicability_event_id",
                    "classification_event_applicability", ["event_id"])
    op.create_index("ix_classification_event_applicability_stock_code",
                    "classification_event_applicability", ["stock_code"])


def downgrade() -> None:
    runs = op.get_bind().execute(sa.text("SELECT count(*) FROM classification_runs")).scalar()
    if runs:
        raise RuntimeError(
            f"classification_runs 에 {runs}건이 있어 downgrade 를 멈춘다. 분류 결과는 LLM 비용을"
            " 들여 만든 것이고, 원문이 지워졌으면 다시 만들 수 없다. 정말 지우려면 결과를 백업한 뒤"
            " 표를 직접 비우고 다시 실행한다."
        )
    op.drop_table("classification_event_applicability")
    op.drop_table("classification_event_entities")
    op.drop_table("classification_events")
    op.drop_table("classification_runs")
    op.drop_table("company_relations")
    op.drop_table("stock_industries")
    op.drop_table("external_companies")
    op.drop_table("industries")
