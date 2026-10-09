from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_item"
    __table_args__ = (UniqueConstraint("user_id", "stock_code", name="uq_watchlist_item_user_stock"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_watchlist_item_user", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stock.code", name="fk_watchlist_item_stock", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
