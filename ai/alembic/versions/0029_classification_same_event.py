"""classification same event: clusters, members, calls

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

같은 사건을 묶는 표 3개를 만든다. 기존 분류 표는 바꾸지 않는다.
설계는 docs/CLASSIFICATION_SAME_EVENT.md 5절, 칼럼 설명은 app/models/classification.py 에 있다.

**downgrade 는 묶음이나 호출 기록이 하나라도 있으면 멈춘다.** 0027 과 같은 이유다. 다시 만들려면
LLM 비용이 든다.

Revision ID: 0029_classification_same_event
Revises: 0028_stock_move_analysis_display
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029_classification_same_event"
down_revision: str | None = "0028_stock_move_analysis_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classification_event_clusters",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("representative_event_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["representative_event_id"], ["classification_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("representative_event_id",
                            name="uq_classification_event_clusters_representative"),
    )

    op.create_table(
        "classification_cluster_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_card_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("fixes", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("status IN ('ok', 'failed')",
                           name="ck_classification_cluster_calls_status"),
        sa.ForeignKeyConstraint(["source_card_id"], ["source_card.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classification_cluster_calls_source_card_id",
                    "classification_cluster_calls", ["source_card_id"])

    op.create_table(
        "classification_event_cluster_members",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("call_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["classification_events.id"]),
        sa.ForeignKeyConstraint(["cluster_id"], ["classification_event_clusters.id"]),
        sa.ForeignKeyConstraint(["call_id"], ["classification_cluster_calls.id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_classification_event_cluster_members_cluster_id",
                    "classification_event_cluster_members", ["cluster_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("classification_event_clusters", "classification_cluster_calls"):
        rows = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        if rows:
            raise RuntimeError(
                f"{table} 에 {rows}건이 있어 downgrade 를 멈춘다. 묶음과 호출 기록은 LLM 비용을 들여"
                " 만든 것이다. 정말 지우려면 결과를 백업한 뒤 표를 직접 비우고 다시 실행한다."
            )
    op.drop_table("classification_event_cluster_members")
    op.drop_table("classification_cluster_calls")
    op.drop_table("classification_event_clusters")
