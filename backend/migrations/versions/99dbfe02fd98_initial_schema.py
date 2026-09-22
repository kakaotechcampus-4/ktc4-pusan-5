"""initial schema

Revision ID: 99dbfe02fd98
Revises:
Create Date: 2026-09-18 14:57:40.584125

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '99dbfe02fd98'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """지금까지 create_all 로 만들어오던 스키마 전체를 옮겨오는 baseline.

    Base.metadata.create_all(bind=op.get_bind())를 그대로 호출하면 이 revision이
    실행되는 시점의(=이후 revision들이 반영된) 모델 코드를 기준으로 테이블을 만들어서,
    빈 DB에 처음부터 head까지 올릴 때 뒤따르는 revision과 중복 생성 충돌이 난다.
    그래서 이 revision을 만든 시점의 스키마를 --autogenerate 로 고정해 못박아둔다.
    이후 스키마 변경은 이 파일이 아니라 새 revision으로만 반영한다.
    """
    op.create_table('channel',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('telegram_handle', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('grade', sa.String(length=1), nullable=True),
    sa.Column('reviewed_by', sa.String(length=50), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('category', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('telegram_handle')
    )
    op.create_table('concepts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('category', sa.String(length=120), nullable=False),
    sa.Column('extra_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('related', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('quiz', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_concepts_slug'), 'concepts', ['slug'], unique=True)
    op.create_table('news',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('publisher', sa.String(length=100), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('cleaned_text', sa.Text(), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('url')
    )
    op.create_index(op.f('ix_news_published_at'), 'news', ['published_at'], unique=False)
    op.create_table('report',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('report_type', sa.String(length=20), nullable=False),
    sa.Column('stock_code', sa.String(length=12), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('verdict', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kakao_id', sa.String(length=50), nullable=False),
    sa.Column('nickname', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_kakao_id'), 'users', ['kakao_id'], unique=True)
    op.create_table('report_block',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('report_id', sa.BigInteger(), nullable=False),
    sa.Column('block_type', sa.String(length=20), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('claim', sa.String(length=300), nullable=True),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['report.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('source_card',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('card_type', sa.String(length=50), nullable=False),
    sa.Column('stock_code', sa.String(length=12), nullable=True),
    sa.Column('event_date', sa.Date(), nullable=True),
    sa.Column('channel_id', sa.Integer(), nullable=True),
    sa.Column('source_name', sa.String(length=100), nullable=True),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('cleaned_text', sa.Text(), nullable=True),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['channel_id'], ['channel.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_source_card_payload_gin', 'source_card', ['payload'], unique=False, postgresql_using='gin')
    op.create_index('idx_source_card_stock_date', 'source_card', ['stock_code', 'event_date'], unique=False)
    op.create_index('idx_source_card_tags_gin', 'source_card', ['tags'], unique=False, postgresql_using='gin')
    op.create_index('idx_source_card_type', 'source_card', ['card_type'], unique=False)
    op.create_table('report_citation',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('report_id', sa.BigInteger(), nullable=False),
    sa.Column('block_id', sa.BigInteger(), nullable=True),
    sa.Column('source_card_id', sa.BigInteger(), nullable=False),
    sa.Column('excerpt', sa.Text(), nullable=True),
    sa.Column('citation_type', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['block_id'], ['report_block.id'], ),
    sa.ForeignKeyConstraint(['report_id'], ['report.id'], ),
    sa.ForeignKeyConstraint(['source_card_id'], ['source_card.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('report_citation')
    op.drop_index('idx_source_card_type', table_name='source_card')
    op.drop_index('idx_source_card_tags_gin', table_name='source_card', postgresql_using='gin')
    op.drop_index('idx_source_card_stock_date', table_name='source_card')
    op.drop_index('idx_source_card_payload_gin', table_name='source_card', postgresql_using='gin')
    op.drop_table('source_card')
    op.drop_table('report_block')
    op.drop_index(op.f('ix_users_kakao_id'), table_name='users')
    op.drop_table('users')
    op.drop_table('report')
    op.drop_index(op.f('ix_news_published_at'), table_name='news')
    op.drop_table('news')
    op.drop_index(op.f('ix_concepts_slug'), table_name='concepts')
    op.drop_table('concepts')
    op.drop_table('channel')
