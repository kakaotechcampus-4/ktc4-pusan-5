"""Make users.email nullable (카카오 이메일 수집 중단).

Revision ID: 20260925_01
Revises: 20260922_01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20260925_01'
down_revision: Union[str, Sequence[str], None] = '20260922_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'email',
               existing_type=sa.String(length=255),
               nullable=True)


def downgrade() -> None:
    # NOT NULL 로 되돌리기 전에 비어 있는 값을 채운다
    op.execute("UPDATE users SET email = '' WHERE email IS NULL")
    op.alter_column('users', 'email',
               existing_type=sa.String(length=255),
               nullable=False)
