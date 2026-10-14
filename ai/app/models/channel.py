"""텔레그램 채널. **backend 가 관리하는 표다.** 여기 둔 것은 FK 대상과 채널 행 등록용이다.

구조 변경은 backend 몫이라 ai/alembic 은 이 표를 비교하지도 바꾸지도 않는다
(alembic/env.py 의 EXTERNAL_TABLES). 칼럼은 backend `app/models/channel.py` 와 맞춘다.

수집기는 처음 보는 채널을 행으로 등록만 한다. 이미 있는 행은 건드리지 않는다 —
등급(grade)·검수 정보는 사람이 채우는 값이라 수집기가 넣으면 검수 전 값이 검수된 것처럼 보인다.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Channel(Base):
    __tablename__ = "channel"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # t.me/<telegram_handle>. analyst_reports.source_category 의 텔레그램 채널명과 같은 값이다
    telegram_handle: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    grade: Mapped[str | None] = mapped_column(String(1))  # A/B/C/D. 사람이 검수하기 전엔 NULL
    reviewed_by: Mapped[str | None] = mapped_column(String(50))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[str | None] = mapped_column(String(50))
    # backend 첫 리비전이 DB 기본값 없이 만들었다. 넣을 때 값을 준다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
