"""주요 지표별 마지막 정상값과 수집 상태. 날짜가 지난 정상값도 보존한다."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshot"

    code: Mapped[str] = mapped_column(String(24), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    change: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    observation_date: Mapped[date | None] = mapped_column(Date)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
