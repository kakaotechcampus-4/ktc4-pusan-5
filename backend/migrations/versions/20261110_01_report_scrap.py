"""Add report_scrap table.

Revision ID: 20261110_01
Revises: 20261031_01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20261110_01'
down_revision: str | Sequence[str] | None = '20261031_01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('report_scrap',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('report_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_report_scrap_user', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'report_id', name='uq_report_scrap_user_report')
    )
    op.create_index(op.f('ix_report_scrap_user_id'), 'report_scrap', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_report_scrap_user_id'), table_name='report_scrap')
    op.drop_table('report_scrap')
