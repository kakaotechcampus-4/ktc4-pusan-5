"""
모든 근거 카드가 들어오는 단일 테이블.
"""
from datetime import UTC, date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.channel import Channel

# 확정되는 대로 여기 채워넣기
CARD_TYPES: list[str] = []


class SourceCard(Base):
    __tablename__ = "source_card"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 카드 종류. 분류를 확정하기 전까지는 자유 문자열로 받는다.
    # DB 레벨 CHECK/ENUM 제약은 타입 목록이 굳어진 뒤에 추가.
    card_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # 종목 카드면 종목코드, 시장 전체(시황) 카드면 NULL
    stock_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 텔레그램발 카드일 때만 채움. 뉴스/공시/시세는 NULL.
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channel.id"), nullable=True)
    channel: Mapped["Channel"] = relationship(lazy="joined")

    # 뉴스매체명, 증권사명 등. 채널 없이도 출처를 표시해야 하는 경우 사용.
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # PDF 원문 파싱은 보류, 텍스트(원문+정제본) 위주로 우선 처리.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 타입별 고유 필드 (목표주가/투자의견/등락률/거래대금 등). 구조는 card_type에 따라 다름.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 채널 등급·검증 게이트와 연동될 신뢰도. 지금은 NULL 허용, 검증 로직 붙으면 채움.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("idx_source_card_type", "card_type"),
        Index("idx_source_card_stock_date", "stock_code", "event_date"),
        Index("idx_source_card_tags_gin", "tags", postgresql_using="gin"),
        Index("idx_source_card_payload_gin", "payload", postgresql_using="gin"),
    )