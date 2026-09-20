"""종목 상세의 정상 데이터, 수집 상태, 영속 작업 큐."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Stock(Base):
    __tablename__ = "stock"
    __table_args__ = (
        CheckConstraint("market IN ('KOSPI','KOSDAQ')", name="ck_stock_market"),
        CheckConstraint("listing_status IN ('listed','inactive')", name="ck_stock_listing_status"),
        PrimaryKeyConstraint(name="pk_stock"),
    )
    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(10))
    listing_status: Mapped[str] = mapped_column(String(10), default="listed")
    listed_at: Mapped[date | None] = mapped_column(Date)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockQuoteSnapshot(Base):
    __tablename__ = "stock_quote_snapshot"
    __table_args__ = (
        CheckConstraint(
            "price > 0 AND volume >= 0 AND trading_value >= 0 AND market_cap >= 0",
            name="ck_stock_quote_snapshot_values",
        ),
        PrimaryKeyConstraint(name="pk_stock_quote_snapshot"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_quote_snapshot_stock"), primary_key=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    change: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    change_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(12), default="KIS")
    source_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockMetricSnapshot(Base):
    __tablename__ = "stock_metric_snapshot"
    __table_args__ = (
        CheckConstraint(
            "foreign_ownership IS NULL OR foreign_ownership BETWEEN 0 AND 100",
            name="ck_stock_metric_snapshot_foreign_ownership",
        ),
        PrimaryKeyConstraint(name="pk_stock_metric_snapshot"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_metric_snapshot_stock"), primary_key=True
    )
    per: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    pbr: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    eps: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    bps: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    foreign_ownership: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    week52_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    week52_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(12), default="KIS")
    source_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockDailyPrice(Base):
    __tablename__ = "stock_daily_price"
    __table_args__ = (
        CheckConstraint("adjustment_type = 'raw'", name="ck_stock_daily_price_adjustment"),
        CheckConstraint(
            "volume >= 0 AND low >= 0 AND high >= low AND open >= low AND open <= high AND close >= low AND close <= high",
            name="ck_stock_daily_price_values",
        ),
        PrimaryKeyConstraint(name="pk_stock_daily_price"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_daily_price_stock"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adjustment_type: Mapped[str] = mapped_column(String(12), primary_key=True, default="raw")
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(12), default="KIS")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockCollectionState(Base):
    __tablename__ = "stock_collection_state"
    __table_args__ = (PrimaryKeyConstraint(name="pk_stock_collection_state"),)
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_collection_state_stock"), primary_key=True
    )
    resource: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(48))


class StockCollectionJob(Base):
    __tablename__ = "stock_collection_job"
    __table_args__ = (
        UniqueConstraint(
            "stock_code", "resource", "range_start", "range_end", name="uq_stock_job_range"
        ),
        CheckConstraint(
            "status IN ('queued','running','idle','failed')", name="ck_stock_collection_job_status"
        ),
        CheckConstraint(
            "resource IN ('snapshot','prices','income','eps','stability')", name="ck_stock_collection_job_resource"
        ),
        CheckConstraint(
            "range_end >= range_start AND attempts >= 0",
            name="ck_stock_collection_job_range_attempts",
        ),
        PrimaryKeyConstraint(name="pk_stock_collection_job"),
        Index("ix_stock_job_claim", "status", "next_run_at", "priority"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_collection_job_stock")
    )
    resource: Mapped[str] = mapped_column(String(16))
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))
    priority: Mapped[int] = mapped_column(default=10)
    attempts: Mapped[int] = mapped_column(default=0)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    error_code: Mapped[str | None] = mapped_column(String(48))


class StockDataCoverage(Base):
    __tablename__ = "stock_data_coverage"
    __table_args__ = (
        CheckConstraint("range_end >= range_start", name="ck_stock_data_coverage_range"),
        PrimaryKeyConstraint(name="pk_stock_data_coverage"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_data_coverage_stock"), primary_key=True
    )
    adjustment_type: Mapped[str] = mapped_column(String(12), primary_key=True, default="raw")
    range_start: Mapped[date] = mapped_column(Date, primary_key=True)
    range_end: Mapped[date] = mapped_column(Date, primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
