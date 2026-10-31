"""KIS 국내휴장일조회로 받은 날짜별 개장 여부. 장 운영 판단에 쓴다."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketCalendarDay(Base):
    __tablename__ = "market_calendar"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
