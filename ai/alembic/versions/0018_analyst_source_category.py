"""Preserve source category in the analyst report natural key.

Revision ID: 0018_source_category
Revises: 0001

market으로 통합된 기존 행은 원본 URL에서 invest/daily를 복구한다.
분류를 복구할 수 없으면 전체 변경을 롤백한다.
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_source_category"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyst_reports", sa.Column("source_category", sa.String(32), nullable=True))
    op.execute("""
        UPDATE analyst_reports
        SET source_category = category
        WHERE source = 'naver' AND category IN ('company', 'industry', 'economy', 'invest', 'daily')
    """)
    # 다른 리포트의 URL로 분류하지 않도록 source_id도 대조한다.
    # SQLAlchemy가 정규식의 :api를 바인드 변수로 해석하지 않도록 콜론을 이스케이프한다.
    op.execute(r"""
        WITH original AS (
            SELECT id, regexp_match(end_url,
                '^https?://m[.]stock[.]naver[.]com/(?\:api/)?research/(invest|daily)/([0-9]+)(?:[?#].*)?$'
            ) AS parts
            FROM analyst_reports WHERE source = 'naver' AND category = 'market'
        )
        UPDATE analyst_reports AS report
        SET source_category = original.parts[1]
        FROM original
        WHERE report.id = original.id AND original.parts[2] = report.source_id
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM analyst_reports WHERE source_category IS NULL) THEN
                RAISE EXCEPTION 'Cannot recover source_category. No rows were deleted. '
                    'Inspect legacy source/category/end_url and restore verified original metadata '
                    'before retrying; do not stamp past this migration.';
            END IF;
        END $$
    """)
    op.alter_column(
        "analyst_reports", "source_category", existing_type=sa.String(32), nullable=False
    )
    op.drop_constraint("uq_analyst_report_source_id", "analyst_reports", type_="unique")
    op.create_unique_constraint(
        "uq_analyst_report_source_id", "analyst_reports", ["source", "source_category", "source_id"]
    )


def downgrade() -> None:
    # invest/daily가 같은 market/id로 공존하면 구 제약으로 되돌릴 수 없다.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM analyst_reports
                GROUP BY source, category, source_id HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Cannot restore the old natural key: source/category/source_id '
                    'collisions exist. Keep this revision; no rows were deleted.';
            END IF;
        END $$
    """)
    op.drop_constraint("uq_analyst_report_source_id", "analyst_reports", type_="unique")
    op.create_unique_constraint(
        "uq_analyst_report_source_id", "analyst_reports", ["source", "category", "source_id"]
    )
    op.drop_column("analyst_reports", "source_category")
