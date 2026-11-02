"""link source_card to dart disclosures

공시 원문 FK와 종류 제약을 추가한다. 원문 없이 만든 기존 disclosure 카드가 있으면 중단한다.

기존 공시의 카드는 만들지 않는다. 카드·공개 시각·종목은 앱 코드가 계산하므로
`python -m app.collectors.sources register` 가 채운다(0024 와 같은 이유).

downgrade 는 공시를 가리키는 카드가 하나라도 있으면 중단한다. report_citation·보고서 출처가
그 카드를 인용하고 있을 수 있다.

Revision ID: 0026_source_card_disclosures
Revises: 0025_dart_disclosures
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_source_card_disclosures"
down_revision: str | None = "0025_dart_disclosures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_RAW_SOURCE_CHECK = (
    "(card_type = 'news') = (news_id IS NOT NULL)"
    " AND (card_type = 'pdf') = (analyst_report_id IS NOT NULL)"
    " AND (card_type = 'message') = (telegram_message_id IS NOT NULL)"
)
RAW_SOURCE_CHECK = (
    OLD_RAW_SOURCE_CHECK + " AND (card_type = 'disclosure') = (dart_disclosure_id IS NOT NULL)"
)


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            conflicting bigint;
        BEGIN
            SELECT count(*) INTO conflicting FROM source_card WHERE card_type = 'disclosure';
            IF conflicting > 0 THEN
                RAISE EXCEPTION 'Cannot link source_card to dart_disclosures: % existing card(s) already use card_type disclosure without a raw source row. No rows were changed.', conflicting;
            END IF;
        END $$
    """)
    op.add_column("source_card", sa.Column("dart_disclosure_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_source_card_dart_disclosure_id",
        "source_card",
        "dart_disclosures",
        ["dart_disclosure_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_source_card_dart_disclosure_id", "source_card", ["dart_disclosure_id"]
    )
    op.drop_constraint("ck_source_card_raw_source", "source_card", type_="check")
    op.create_check_constraint("ck_source_card_raw_source", "source_card", RAW_SOURCE_CHECK)


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            linked bigint;
        BEGIN
            SELECT count(*) INTO linked FROM source_card WHERE dart_disclosure_id IS NOT NULL;
            IF linked > 0 THEN
                RAISE EXCEPTION 'Cannot unlink source_card from dart_disclosures: % card(s) point to disclosures. Keep this revision; no rows were deleted.', linked;
            END IF;
        END $$
    """)
    op.drop_constraint("ck_source_card_raw_source", "source_card", type_="check")
    op.create_check_constraint("ck_source_card_raw_source", "source_card", OLD_RAW_SOURCE_CHECK)
    op.drop_constraint("uq_source_card_dart_disclosure_id", "source_card", type_="unique")
    op.drop_constraint("fk_source_card_dart_disclosure_id", "source_card", type_="foreignkey")
    op.drop_column("source_card", "dart_disclosure_id")
