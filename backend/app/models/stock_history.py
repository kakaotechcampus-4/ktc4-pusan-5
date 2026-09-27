"""Historical market cap/relative-strength snapshots and shared KRX cache."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StockPeriodMarket(Base):
    __tablename__ = "stock_period_market"
    __table_args__ = (
        PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_period_market"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_period_market_stock_code_stock"),
        primary_key=True,
    )
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    cap_as_of: Mapped[date | None] = mapped_column(Date)
    cap_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rs: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    rs_as_of: Mapped[date | None] = mapped_column(Date)
    rs_base_date: Mapped[date | None] = mapped_column(Date)
    rs_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KrxHistoricalCache(Base):
    """Shared KRX response by market, kind, and trading date."""

    __tablename__ = "krx_historical_cache"
    __table_args__ = (
        CheckConstraint("kind IN ('stock','index')", name="ck_krx_historical_cache_kind"),
        PrimaryKeyConstraint("market", "kind", "trade_date", name="pk_krx_historical_cache"),
    )
    market: Mapped[str] = mapped_column(String(10), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rows: Mapped[list | dict] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
