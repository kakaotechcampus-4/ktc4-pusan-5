from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JsonList = list[dict[str, Any]]


class Concept(Base):
    """개념 글. 원본은 seeds/concepts/<slug>.json 이고 이 테이블은 그 사본이다."""

    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list)
    category: Mapped[str] = mapped_column(String(120))
    extra_categories: Mapped[list[str] | None] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    related: Mapped[JsonList | None] = mapped_column(JSONB)
    quiz: Mapped[JsonList | None] = mapped_column(JSONB)
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
