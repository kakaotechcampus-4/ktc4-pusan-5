from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Disclosure:
    """공시 한 건. 필드 이름은 DART 응답을 따른다."""

    rcept_no: str  # 접수번호 14자리. 공시 하나에 하나
    corp_code: str  # DART 고유번호 8자리
    corp_name: str
    stock_code: str
    report_nm: str  # 보고서명. 정정이면 "[기재정정]" 이 앞에 붙는다
    flr_nm: str  # 공시 제출인
    rcept_dt: date  # 접수일. 시각은 주지 않는다
    rm: str | None  # 비고 (유: 유가증권시장본부 소관, 연: 연결, 정: 정정 후 등)
