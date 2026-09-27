from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RankingSnapshot(Base):
    """탭별 순위 배열을 한 행으로 교체해 서로 다른 수집 회차가 섞이지 않도록 한다."""

    __tablename__ = "ranking_snapshot"

    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    items: Mapped[list[dict] | None] = mapped_column(JSONB)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
