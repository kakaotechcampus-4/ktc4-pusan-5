"""
텔레그램 채널들의 메타데이터.

grade(A/B/C/D)는 지금 이름만 보고 매긴 초안 상태.
검수가 끝나기 전까지는 신뢰할 수 없는 값이므로, 리포트 생성 로직에서
grade IS NULL 이거나 검수 전 채널을 근거로 쓰지 않도록 별도로 막아야 함.
"""
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Channel(Base):
    __tablename__ = "channel"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 텔레그램 채널 식별자. 공개 채널은 t.me/s/<telegram_handle> 로 로그인 없이 수집됨
    telegram_handle: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # A/B/C/D. 사람이 직접 검수하기 전엔 NULL
    grade: Mapped[str | None] = mapped_column(String(1), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 채널 성격. 값 목록이 아직 안 굳어서 자유 텍스트로 둠.
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )