from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReportScrap(Base):
    """사용자가 스크랩한 보고서.

    report_id 는 ai 가 만드는 `stock_move_analyses.id` 다. 그 표는 ai Alembic 소유라 FK 를 걸지 않는다.
    """

    __tablename__ = "report_scrap"
    __table_args__ = (UniqueConstraint("user_id", "report_id", name="uq_report_scrap_user_report"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_report_scrap_user", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
