"""출처별 연간 재무 스냅샷. 손익과 EPS는 기준 기간으로만 연결한다."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StockAnnualIncome(Base):
    __tablename__ = "stock_annual_income"
    __table_args__ = (
        PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_annual_income"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_annual_income_stock_code_stock"), primary_key=True
    )
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    operating_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(12), default="KIS")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockAnnualEps(Base):
    __tablename__ = "stock_annual_eps"
    __table_args__ = (PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_annual_eps"),)
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_annual_eps_stock_code_stock"), primary_key=True
    )
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    eps: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    debt_ratio: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(12), default="KIS")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockAnnualStability(Base):
    __tablename__ = "stock_annual_stability"
    __table_args__ = (
        PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_annual_stability"),
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_stock_annual_stability_stock_code_stock"),
        primary_key=True,
    )
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    current_ratio: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(12), default="KIS")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
