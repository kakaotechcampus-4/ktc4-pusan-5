"""initial schema

Revision ID: 99dbfe02fd98
Revises:
Create Date: 2026-09-18 14:57:40.584125

"""
from collections.abc import Sequence

from alembic import op

from app.core.database import Base

# revision identifiers, used by Alembic.
revision: str = '99dbfe02fd98'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """create_all 로 만든다. env.py 가 app.models 를 이미 import 해뒀으므로
    Base.metadata 에는 이 시점에 모든 테이블이 등록돼 있다.

    이후 revision부터는 --autogenerate 로 모델과 실제 DB의 diff 만 반영한다.
    이 첫 revision은 diff가 아니라 "지금까지 create_all 로 만들어오던 스키마 전체"를
    한 번에 옮겨오는 baseline이라 예외적으로 직접 호출한다.
    """
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
