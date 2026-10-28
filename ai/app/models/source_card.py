"""공통 자료 목록. source_card.id 가 뉴스·PDF·메시지를 가리키는 **공통 자료 ID** 다.

**backend 가 만든 표를 AI 가 넘겨받았다.** 표는 backend 첫 리비전(99dbfe02fd98)이 만들었고,
그 뒤 구조 변경은 ai/alembic(0022~)이 한다. backend 는 이 표를 비교하지 않고, 행을 읽고
report_citation 으로 인용만 한다. 위의 칼럼은 backend 모델 그대로이고 아래 세 FK 가 추가분이다.

원문을 여기에 복제하지 않는다. 종류별 원문 표의 행 하나를 FK 로 가리킨다.

    card_type   원문 표                 수집 경로 예
    news        news                   네이버 뉴스 검색, 텔레그램 메시지 링크
    pdf         analyst_reports        네이버 증권 리서치, 텔레그램 첨부
    message     telegram_messages      텔레그램 공개 채널 미리보기, 로그인 계정

자료 형태(card_type), 원 발행처(source_name), 수집 경로(원문 표의 source·collected_via)는
서로 다른 값이다. 증권사 PDF 를 텔레그램에서 받았다면 형태는 pdf, 발행처는 증권사,
경로는 텔레그램 첨부다. 기업·산업 분류는 여기 두지 않는다 — 원문 저장과 분리한다.

raw_text·cleaned_text·source_url 은 backend 가 원문을 직접 담던 카드용이다. 위 세 종류의
카드는 비워 둔다. 원문은 FK 로 따라가 읽는다(repositories/source_card.py 의 get_sources).
"""

from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 원문 표를 가리키는 카드 종류. 이 밖의 card_type(backend 가 쓸 시세·공시 카드 등)은
# 세 FK 를 모두 비워야 한다.
RAW_CARD_TYPES = ("news", "pdf", "message")


class SourceCard(Base):
    __tablename__ = "source_card"
    __table_args__ = (
        Index("idx_source_card_type", "card_type"),
        Index("idx_source_card_stock_date", "stock_code", "event_date"),
        Index("idx_source_card_tags_gin", "tags", postgresql_using="gin"),
        Index("idx_source_card_payload_gin", "payload", postgresql_using="gin"),
        # 원문 한 행에 카드 하나. 등록 처리를 다시 돌려도 같은 원문의 카드가 늘지 않는다.
        UniqueConstraint("news_id", name="uq_source_card_news_id"),
        UniqueConstraint("analyst_report_id", name="uq_source_card_analyst_report_id"),
        UniqueConstraint("telegram_message_id", name="uq_source_card_telegram_message_id"),
        # 종류에 맞는 원문 하나만 가리킨다. news 카드는 news_id 만, pdf 는 analyst_report_id 만,
        # message 는 telegram_message_id 만 채운다. 그 밖의 종류는 셋 다 비운다.
        CheckConstraint(
            "(card_type = 'news') = (news_id IS NOT NULL)"
            " AND (card_type = 'pdf') = (analyst_report_id IS NOT NULL)"
            " AND (card_type = 'message') = (telegram_message_id IS NOT NULL)",
            name="ck_source_card_raw_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    card_type: Mapped[str] = mapped_column(String(50))
    stock_code: Mapped[str | None] = mapped_column(String(12))
    event_date: Mapped[date | None] = mapped_column(Date)
    # 텔레그램에서 온 카드(메시지, 텔레그램 첨부 PDF)만 채운다
    channel_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("channel.id"))
    source_name: Mapped[str | None] = mapped_column(String(100))  # 원 발행처
    source_url: Mapped[str | None] = mapped_column(String(500))
    raw_text: Mapped[str | None] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    # backend 첫 리비전이 DB 기본값 없이 만들었다. 넣을 때 값을 준다.
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    news_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("news.id", name="fk_source_card_news_id")
    )
    analyst_report_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("analyst_reports.id", name="fk_source_card_analyst_report_id")
    )
    telegram_message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("telegram_messages.id", name="fk_source_card_telegram_message_id")
    )
