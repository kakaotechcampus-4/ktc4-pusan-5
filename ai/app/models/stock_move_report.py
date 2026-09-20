"""③ 산출물 — 우리가 생성한 종목 변동 요인 보고서.

한 행 = 보고서 한 회차. `analyst_reports` 가 "증권사 애널리스트가 쓴 원문" 이라면
이건 "그 종목이 왜 그렇게 움직였는지 우리가 LLM 으로 만든 설명" 이다.
backend 의 `report` / `report_block` / `report_citation` 과도 다른 계통이라
이름을 `stock_move_report` 접두사로 묶어 같은 Postgres 에서 겹치지 않게 했다.

**INSERT only 다. UPDATE 하지 않는다.** 시스템 프롬프트가 "이전 회차를 언급하지
않는다" 고 못박아서 각 회차는 독립 문서다. 같은 종목·같은 기준시각을 다시 만들어도
덮어쓰지 않고 새 행으로 쌓는다. 그래서 자연키 (ticker, target_date, as_of) 에
UNIQUE 를 걸 수 없다 — 인덱스로만 둔다.

**검증 실패 건도 버리지 않는다.** 스키마를 어긴 보고서가 왜 나왔는지는 그 보고서를
봐야 알 수 있다. 그래서 정규화 칼럼은 거의 전부 nullable 이고, 원본은 `raw_json` 에
통째로 남는다. "왜 NULL 인가" 는 `parse_status` 가 말한다.

**검수 판정은 여기 없다.** AI 서버(적재)와 검수자가 같은 행을 건드리면 단방향이
깨지므로 `stock_move_report_reviews` 로 분리했다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockMoveReport(Base):
    __tablename__ = "stock_move_reports"
    __table_args__ = (
        # 그 종목의 최신 회차를 뽑는 인덱스. UNIQUE 가 아니다 — 같은 기준시각의
        # 재생성도 새 행이라 유일성을 걸면 적재가 막힌다.
        Index("ix_stock_move_report_ticker_as_of", "ticker", "as_of"),
        Index("ix_stock_move_report_target_date", "target_date"),
        # backend 조회는 verify_status = passed 를 전제한다. 미검증·실패 행이
        # 대부분이 될 수 있어서 부분 인덱스로 둔다.
        Index(
            "ix_stock_move_report_passed",
            "ticker",
            "as_of",
            postgresql_where=text("verify_status = 'passed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 산출물 역추적용. runs/<타임스탬프>/parsed/<run_id>.json 으로 되돌아갈 수 있어야
    # 오적재 원인을 파일 하나까지 좁힐 수 있다. 래퍼가 실험 환경 산출물이라 없을 수도 있다.
    run_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- 보고서가 무엇에 대한 것인가 ----------------------------------
    # 칼럼명을 프롬프트 출력 키(ticker/name)와 맞췄다. analyst_reports 는
    # item_code/item_name 이지만, 여기는 적재가 JSON 키 → 칼럼 1:1 매핑이라
    # 이름이 어긋나면 옮겨 담다가 실수가 난다.
    ticker: Mapped[str | None] = mapped_column(String(6), nullable=True)
    # 종목 마스터가 생기면 중복이지만 그때도 남긴다. 프롬프트가 회차 간 참조를 금지해
    # 각 회차가 독립 문서이므로, 생성 시점의 종목명은 그 문서의 일부다. 종목명은 바뀐다.
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 출력 키는 date 지만 칼럼명으로 쓰면 날짜 타입명과 겹쳐 읽기 나쁘다.
    # 프롬프트 **입력**이 같은 값을 target_date 라고 부르므로 그 이름을 썼다.
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 프롬프트 출력은 "HH:MM" 문자열이다. target_date 와 합쳐 KST aware datetime 으로
    # 저장한다 — 루트 CLAUDE.md 가 naive datetime 을 금지하고 응답은 ISO 8601 이어야 한다.
    # 원본 "15:30" 은 raw_json 에 그대로 남아 진실의 출처가 둘로 갈리지 않는다.
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # float 로 받으면 -2.01 이 -2.0100000000000002 로 굳는다. 루트 CLAUDE.md 가
    # "가공하지 않은 값" 을 요구하므로 DB 가 값을 흔들면 안 된다.
    # 정밀도는 analyst_reports.upside_pct 와 같게 맞췄다.
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    # explained | partially_explained | no_clear_cause
    #
    # 이하 LLM 이 채우는 값들은 Postgres ENUM 이나 CHECK 를 걸지 않는다. 두 가지 이유다.
    #   1. 스키마를 어긴 값(size_fit="medium" 같은)이 들어오면 INSERT 가 거절된다.
    #      원인 분석 자료를 남기려고 적재하는 건데 정작 깨진 행만 못 들어온다.
    #   2. alembic 이 없고 create_all 은 이미 있는 타입을 갱신하지 않는다.
    #      값 하나 늘리려면 운영 DB 에 ALTER TYPE 을 손으로 쳐야 한다.
    # analyst_reports 의 category/source/body_status 도 같은 이유로 String 이다.
    verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # --- summary 네 칸 ------------------------------------------------
    # counter 만 NULL 이 **정상값**이다(방향이 어긋나는 재료가 없는 날, 그리고
    # no_clear_cause 인 날). 나머지 셋의 NULL 은 파싱이 깨졌다는 뜻이다.
    # 둘을 칼럼만 보고 구분할 수 없어서 parse_status 를 따로 둔다.
    summary_move: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_main_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_counter: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_unexplained: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- 표로 펴지 않는 것 --------------------------------------------
    # 화면이 통째로 받아 쓰는 덩어리라 행으로 쪼갤 이유가 없다.
    terms: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{plain, term}]
    # {bullish: [...], bearish: [...], neutral: [...]}
    # 프롬프트는 항목을 문자열로도 {"text": ..., "watch": true} 객체로도 낸다.
    # 둘 다 정상이므로 파서가 흡수해 여기서는 객체 형태로 통일해 둔다
    # (정규화 규칙은 repositories/stock_move_report.py 참고). 원본 혼용은 raw_json 에 남는다.
    background: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 검수용. 화면에 나가지 않지만 사후 환각 추적 수단이 이것뿐이라 반드시 넣는다.
    # 노출 제어는 backend 응답 단계에서 한다.
    not_found: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # 보고서 JSON 통째. 파싱 성공이면 보고서 객체, 실패면 래퍼 객체를 그대로 넣는다.
    # 어느 쪽인지는 parse_status 가 말한다. 정규화 칼럼과 별개로 두는 이유는
    # 스키마 위반 케이스가 반드시 나오고, 그때 칼럼에 안 담긴 값이 사라지면 안 되기 때문이다.
    raw_json: Mapped[dict] = mapped_column(JSONB)

    # --- 적재 계층이 본 것 --------------------------------------------
    # ok | schema_violation | parse_failed
    parse_status: Mapped[str] = mapped_column(String(20), default="ok")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- 근거 검증 판정 -----------------------------------------------
    # **적재 모듈이 판정하지 않는다.** 검증기(실험 레포에 있다)의 결과를 인자로 받아
    # 채운다. 판정과 적재를 분리해야 한쪽을 고쳐도 다른 쪽이 안 흔들린다.
    # 기본값이 not_verified 인 이유: failed 를 기본으로 두면 "검증해서 떨어진 것" 과
    # 구분이 안 되고, passed 를 기본으로 두면 미검증 보고서가 backend 조회로 샌다.
    verify_status: Mapped[str] = mapped_column(String(20), default="not_verified")
    verify_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 후속 과제: 지금 시스템 프롬프트에 버전 문자열이 없다. 생기면 채운다.
    # 이름은 tag_messages.py 의 PROMPT_VERSION 관례를 따랐다.
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # LLM 이 보고서를 만든 시각. 실행 기록 래퍼에 타임스탬프가 없어서(duration_ms 뿐이다)
    # 실행 디렉터리 이름에서 받아 채운다. 루트 CLAUDE.md 가 브리핑 응답에
    # generatedAt 을 요구하므로 칸은 지금 만들어 둔다.
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 적재 시각은 DB 시계로 통일한다(analyst_reports.collected_at 관례).
    # 배치가 여러 대가 되어도 적재 순서가 한 시계로 보존된다.
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 래퍼의 verdict / n_factors / n_sources 는 담지 않는다. final_text 안의 값을
    # 다시 센 것이라 두 군데 있으면 어긋났을 때 무엇을 믿을지 문제가 된다.
    # 단일 출처는 final_text 다. duration_ms / cost_usd 도 운영 지표라 여기 두지 않는다.

    factors: Mapped[list["StockMoveReportFactor"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="StockMoveReportFactor.order_index",
    )


class StockMoveReportFactor(Base):
    """보고서가 든 원인 하나. 프롬프트 상한은 4개지만 **초과분을 잘라내지 않는다.**

    상한 위반 탐지는 실행 점검 스크립트 담당이고, 적재가 말없이 자르면 그 검사가
    영원히 통과한다. 여기서는 그대로 넣고 로그에만 남긴다.
    """

    __tablename__ = "stock_move_report_factors"
    __table_args__ = (
        # 순서가 곧 중요도라 (보고서, 순서) 가 자연키다. 같은 순서가 둘이면 적재 버그다.
        UniqueConstraint("report_id", "order_index", name="uq_stock_move_report_factor_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("stock_move_reports.id", ondelete="CASCADE"), index=True
    )

    # 0-base. 프롬프트가 "최대 4개, 중요도 순" 이라고 정해서 배열 순서 자체가 정보다.
    order_index: Mapped[int] = mapped_column(Integer)

    claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    stance: Mapped[str | None] = mapped_column(String(16), nullable=True)  # bullish|bearish|neutral
    direction_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # sufficient | partial | insufficient
    size_fit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unconfirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    report: Mapped["StockMoveReport"] = relationship(back_populates="factors")
    sources: Mapped[list["StockMoveReportFactorSource"]] = relationship(
        back_populates="factor",
        cascade="all, delete-orphan",
        order_by="StockMoveReportFactorSource.order_index",
    )


class StockMoveReportFactorSource(Base):
    """원인 하나가 기댄 출처 하나.

    quote / match / is_market_recap 은 화면에 나가지 않는다. 그래도 전부 넣는다 —
    사후에 "이 문장이 정말 원문에 있었나" 를 되짚을 수단이 이것뿐이다.
    노출 제어는 backend 응답 단계에서 한다. 적재 단계에서 빼면 되돌릴 방법이 없다.
    """

    __tablename__ = "stock_move_report_factor_sources"
    __table_args__ = (
        UniqueConstraint("factor_id", "order_index", name="uq_stock_move_report_source_order"),
        # 같은 URL 이 여러 보고서에서 얼마나 인용됐는지 되짚을 때 쓴다.
        Index("ix_stock_move_report_source_url", "url"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    factor_id: Mapped[int] = mapped_column(
        ForeignKey("stock_move_report_factors.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)

    # 출처 **종류**다. 채널명이 아니다 — 채널명은 channel 이 말한다.
    # analyst_reports.source (naver | telegram) 관례를 따랐다.
    # 지금은 전부 telegram 이지만 뉴스·리포트 PDF 가 붙으면 소스별 오탐률을 갈라 봐야 한다.
    # 그때 칼럼을 추가하면 이미 쌓인 데이터가 전부 미상이 되므로 지금 만든다.
    source: Mapped[str] = mapped_column(String(16), default="telegram")

    channel: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    datetime_kst: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 원문 그대로 40자 이내 발췌. 한 글자만 달라도 근거 검증에서 떨어진다.
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    match: Mapped[str | None] = mapped_column(String(16), nullable=True)  # direct | indirect
    is_market_recap: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    factor: Mapped["StockMoveReportFactor"] = relationship(back_populates="sources")


class StockMoveReportReview(Base):
    """사람이 내린 검수 판정. **이번 PR 은 표만 만들고 쓰지 않는다.**

    보고서 행에 칼럼으로 붙이지 않은 이유: AI 서버(적재)와 검수 쪽이 같은 행을
    건드리면 단방향이 깨진다. 보고서는 INSERT only 로 두고 판정만 여기 쌓는다.
    한 보고서에 판정이 여러 번 달릴 수 있어 UNIQUE 를 걸지 않았다.
    """

    __tablename__ = "stock_move_report_reviews"
    __table_args__ = (Index("ix_stock_move_report_review_report", "report_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("stock_move_reports.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(20))  # approved | rejected | hold
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
