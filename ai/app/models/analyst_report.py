"""② core — 증권사 애널리스트 리포트.

한 행 = 리포트 한 편. 지금은 네이버 증권 리서치만 넣지만 `source` 컬럼으로
텔레그램·한경컨센서스 같은 다른 출처를 같은 표에 받는다.

PDF 원본은 저장하지 않는다. 임시 폴더에 받아 텍스트만 뽑고 파일은 지운다.
    - 1주일치 PDF만 해도 수백 MB인데, 우리가 쓰는 건 본문 텍스트뿐이다.
    - `attach_url`이 살아 있어서(2025-12 리포트도 지금 200으로 응답) 파서를
      고치면 다시 받아 재파싱할 수 있다. 그래서 버려도 되는 것이다.
    - `pdf_sha256`을 남겨 같은 파일이 다른 출처로 또 들어와도 알아본다.

요약(summary_text)과 본문(body_text)을 따로 두는 이유: 요약은 네이버가 준
확정 텍스트(평균 517자)고 본문은 우리가 PDF에서 뽑은 것이라 품질이 다르다.
섞으면 나중에 무엇을 인용했는지 못 가린다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalystReport(Base):
    __tablename__ = "analyst_reports"
    __table_args__ = (
        # researchId는 카테고리마다 별도 시퀀스다(company 96141, industry 46078).
        # 그래서 (출처, 카테고리, 원본ID)가 자연키다. 재수집해도 중복이 안 생긴다.
        UniqueConstraint("source", "category", "source_id", name="uq_analyst_report_source_id"),
        Index("ix_analyst_report_code_date", "item_code", "write_date"),
        Index("ix_analyst_report_date", "write_date"),
        Index("ix_analyst_report_broker_date", "broker", "write_date"),
        # 본문 추출 대기열을 뽑는 인덱스
        Index("ix_analyst_report_body_status", "body_status", "write_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # --- 출처 --------------------------------------------------------
    source: Mapped[str] = mapped_column(String(16), default="naver")  # naver | telegram
    source_id: Mapped[str] = mapped_column(String(64))  # 네이버 researchId

    # 리포트 **종류**. 출처가 아니다 — 출처는 source 가 말한다.
    #     company    종목분석      특정 종목 하나
    #     industry   산업분석      업종·테마. 종목 여러 개
    #     economy    경제분석      금리·물가·고용 같은 거시지표와 통화정책
    #     market     시황·투자전략  장마감·브리핑·자산배분·포트폴리오
    #
    # 네이버는 invest(투자전략)와 daily(시황)를 따로 주는데 **합쳐서 market 으로 받는다.**
    # 네이버 229건으로 채점해보니 둘이 안 갈린다(3종 62~69% → 합치면 84~86%).
    # 네이버 라벨 자체가 흔들려서다 — 같은 'Weekly' 가 증권사에 따라 invest 이기도
    # daily 이기도 하다. 증권사가 자기 발간물을 어디에 올릴지 정하는 거라
    # 제목·본문으로는 복원이 안 된다. 구분이 안 되는 걸 나눠두면 그 칼럼을 못 믿는다.
    category: Mapped[str] = mapped_column(String(16))

    # --- 대상 --------------------------------------------------------
    # 종목분석만 종목코드가 있다. 산업·경제·전략·데일리는 NULL이다.
    item_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    item_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- 발행 --------------------------------------------------------
    # 애널리스트 개인명은 저장하지 않는다. 출처는 "@@증권이 제시"로 충분하고,
    # 네이버가 그 값을 안 줘서 PDF 서명줄에서 추정해야 하는데 채움률 41%에
    # 오탐까지 섞였다. 없는 값을 추정해 넣느니 증권사만 확실히 적는다.
    # 발행기관. 네이버는 항상 brokerName 을 주지만, 텔레그램 재배포물엔 증권사가 아닌
    # 발행처(기업 IR 자료, 스터닝밸류 리서치·쟁글 같은 독립 리서치)가 섞여 들어오고
    # 스캔 이미지 PDF 는 본문이 없어 아무것도 못 뽑는다. 그때 채널명을 넣으면 거짓이 되므로 NULL.
    broker: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    write_date: Mapped[date] = mapped_column(Date)
    read_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- 네이버가 구조화해서 주는 값 ---------------------------------
    # PDF에서 뽑으면 성공률이 10% 안팎이라(텍스트 추출이 표를 흩어놓는다) 여기 값만 쓴다.
    opinion: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 매수/중립/…
    goal_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price_at_write: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 목표주가 대비 상승여력. (목표주가 - 작성시점 주가) / 작성시점 주가.
    upside_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    # ⚠️ 네이버 응답의 `prevGoalPrice`는 직전 목표주가가 **아니다**. 저장하지 않는다.
    #    종목분석 118건 전부에서 `prevGoalPrice == priceAtWriteDate` 였고,
    #    PDF 원문과 대조해 확인했다 — 미래에셋증권(006800) 유안타 리포트는
    #    PDF에 "직전 목표주가 75,000원 / 현재주가 35,050원"이라고 적혀 있는데
    #    API는 prevGoalPrice=35,050을 준다. 즉 현재가의 중복이다.
    #    직전 목표주가가 필요하면 같은 (broker, item_code)의 이전 행을 보면 된다.
    #    원본은 raw_api_calls에 그대로 남아 있으니 나중에 검증할 수 있다.

    # --- 산업분석 전용 -------------------------------------------------
    # 산업 리포트는 종목이 아니라 업종에 의견을 낸다. 그래서 opinion/goal_price 가 아니라
    # 여기에 들어간다. 네이버는 이 값을 안 주므로 PDF 앞부분에서 뽑는다.
    #   "투자의견 Overweight / 비중확대, 유지 / Top picks: 인텔리안테크, RFHIC"
    # 종목별 목표주가는 담지 않는다 — 리포트 하나에 종목이 여러 개라 칼럼에 안 들어가고,
    # 본문의 "목표주가" 등장은 대부분(39회 중 36회) 리포트 끝 컴플라이언스 부록이라
    # 잘못 뽑으면 과거 의견을 현재 의견으로 싣게 된다.
    sector_opinion: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # 비중확대 | 중립 | 비중축소
    top_picks: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    summary_html: Mapped[str | None] = mapped_column(Text, nullable=True)  # 원문 그대로
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 태그 제거
    summary_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- 원문 PDF ----------------------------------------------------
    end_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attach_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    pdf_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pdf_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)

    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pending: 아직 안 받음 / ok / empty: 텍스트 0자(스캔본 추정) / failed / skipped: 첨부 없음
    body_status: Mapped[str] = mapped_column(String(16), default="pending")
    body_extractor: Mapped[str | None] = mapped_column(String(16), nullable=True)  # pdftotext|pypdf
    body_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- 수집 이력 ---------------------------------------------------
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
