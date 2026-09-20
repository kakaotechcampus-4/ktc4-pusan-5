"""
report 결과물이 최종적으로 쌓이는 테이블.
report_block: 리포트를 구성하는 블록(이유/참고/확인 못한 것 등) 단위.
report_citation: 어떤 블록(또는 리포트 전체)이 어떤 근거카드를 인용했는지 (역추적용 다리).
"""
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Report(Base):
    __tablename__ = "report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    report_type: Mapped[str] = mapped_column(String(20), nullable=False)  # STOCK / MARKET
    stock_code: Mapped[str | None] = mapped_column(String(12), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 통짜 텍스트 요약. 구조화된 본문은 report_block으로 관리한다.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)  # CONFIRMED / UNCONFIRMED 등
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")  # DRAFT/GATED/PUBLISHED

    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    blocks: Mapped[list["ReportBlock"]] = relationship(back_populates="report")
    citations: Mapped[list["ReportCitation"]] = relationship(back_populates="report")


class ReportBlock(Base):
    """이유(FACTOR) / 참고(NOTE) / 확인 못한 것(UNCONFIRMED) 등 리포트 본문의 블록 하나.

    FACTOR는 claim(한줄 주장)+detail(설명)을 함께 쓰고, NOTE/UNCONFIRMED는
    claim 없이 detail만 채운다. block_type 값 목록은 카드 분류처럼 아직
    확정 전이라 자유 문자열로 둔다.
    """

    __tablename__ = "report_block"
    __table_args__ = (
        # report_citation이 (block_id, report_id) 복합 FK로 이 테이블을 참조하기 위한 대상.
        # Postgres 복합 FK는 참조 대상 컬럼 조합에 명시적 unique 제약이 있어야 해서 추가.
        UniqueConstraint("id", "report_id", name="uq_report_block_id_report_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id"), nullable=False)

    block_type: Mapped[str] = mapped_column(String(20), nullable=False)  # FACTOR / NOTE / UNCONFIRMED
    order_index: Mapped[int] = mapped_column(nullable=False, default=0)

    claim: Mapped[str | None] = mapped_column(String(300), nullable=True)  # FACTOR 전용
    detail: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    report: Mapped["Report"] = relationship(back_populates="blocks")
    # citation.report_id는 report_id 단독 FK(report)와 (block_id, report_id) 복합 FK(block)
    # 양쪽에서 같이 쓰인다. 의도된 중복이라 SAWarning을 overlaps로 명시해 끈다.
    citations: Mapped[list["ReportCitation"]] = relationship(back_populates="block", overlaps="citations")


class ReportCitation(Base):
    __tablename__ = "report_citation"
    __table_args__ = (
        # block_id가 채워져 있으면 그 block이 반드시 이 row의 report_id 소속이도록 강제한다.
        # block_id가 NULL(리포트 전체 인용)이면 복합 FK는 검사되지 않는다.
        ForeignKeyConstraint(
            ["block_id", "report_id"],
            ["report_block.id", "report_block.report_id"],
            name="fk_report_citation_block_report",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id"), nullable=False)
    # 블록 단위 인용이면 채워짐. 리포트 전체에 걸린 인용(블록으로 안 쪼개진 경우)이면 NULL.
    block_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_card_id: Mapped[int] = mapped_column(ForeignKey("source_card.id"), nullable=False)

    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)  # 원문 재게시 아님, 짧은 발췌만
    # 인용된 발췌가 원문 그대로인지(DIRECT), 요약/의역인지(PARAPHRASE). 값 목록은 자유 문자열.
    citation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="DIRECT")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    report: Mapped["Report"] = relationship(back_populates="citations", overlaps="citations")
    block: Mapped["ReportBlock | None"] = relationship(back_populates="citations", overlaps="citations,report")