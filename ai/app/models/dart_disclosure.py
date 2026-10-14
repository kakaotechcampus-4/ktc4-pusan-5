"""DART 공시 목록. 한 행 = 공시 한 건(접수번호).

공시는 회사가 공식으로 낸 발표라, 뉴스·텔레그램에 그 종목 얘기가 없는 날에도 종목 고유의
재료를 찾을 수 있는 곳이다. 지금은 목록(제목·제출인·접수일)만 저장한다. 본문은 받지 않는다.

**접수 시각이 없다.** DART 목록 API 는 접수일(rcept_dt)만 준다. 그래서 수집기가 처음 본 시각을
first_seen_at 에 남긴다. 장중에 자주 수집할수록 이 값이 실제 공시 시각에 가까워진다.
기준 시각 이전 자료만 쓰는 보고서는 rcept_dt 가 아니라 first_seen_at 으로 거른다.

**처음 저장한 행을 바꾸지 않는다.** 같은 접수번호를 다시 받으면 건너뛴다. 정정 공시는
DART 가 새 접수번호를 주므로 별도 행이 된다.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


class DartDisclosure(Base):
    __tablename__ = "dart_disclosures"
    __table_args__ = (
        UniqueConstraint("rcept_no", name="uq_dart_disclosure_rcept_no"),
        Index("ix_dart_disclosures_stock_date", "stock_code", "rcept_dt"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rcept_no: Mapped[str] = mapped_column(String(14))  # 접수번호
    corp_code: Mapped[str] = mapped_column(String(8))  # DART 고유번호
    corp_name: Mapped[str] = mapped_column(String(200))
    stock_code: Mapped[str] = mapped_column(String(6))
    report_nm: Mapped[str] = mapped_column(Text)  # 보고서명
    flr_nm: Mapped[str] = mapped_column(String(200))  # 제출인
    rcept_dt: Mapped[date] = mapped_column(Date)  # 접수일. 시각 없음
    rm: Mapped[str | None] = mapped_column(String(20))  # 비고
    # 이 수집기가 처음 본 시각. 공시가 그 이전에 나와 있었다는 것만 확실하다
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def url(self) -> str:
        """DART 공시 뷰어 주소. 보고서의 출처 주소로 쓴다."""
        return VIEWER_URL + self.rcept_no
