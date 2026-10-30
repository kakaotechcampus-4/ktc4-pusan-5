"""코스피 시가총액 기준 상위 30개 종목을 코드로 고정

수집기가 이 목록 전체의 현재가를 정기 수집하므로 개수가 KIS 호출량을 정한다.
늘릴 때는 STOCK_QUOTE_INTERVAL_SECONDS·KIS_REQUEST_INTERVAL_SECONDS 를 함께 본다.

MVP_STOCKS 의 순위를 고치면 MVP_STOCKS_AS_OF 도 그 조회 시각으로 같이 갱신한다.
"""

from datetime import datetime, timedelta, timezone
from typing import NamedTuple

# MVP_STOCKS 의 순위 조회한 시각
MVP_STOCKS_AS_OF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone(timedelta(hours=9)))

# sector 는 KIS inquire-price 의 bstp_kor_isnm 을 2026-10-06 에 종목별로 조회한 값
# 표기는 KRX 업종지수를 따름
class MvpStock(NamedTuple):
    rank: int
    code: str
    name: str
    sector: str


MVP_STOCKS: tuple[MvpStock, ...] = (
    MvpStock(1, "005930", "삼성전자", "전기전자"),
    MvpStock(2, "000660", "SK하이닉스", "전기전자"),
    MvpStock(3, "005935", "삼성전자우", "전기전자"),
    MvpStock(4, "402340", "SK스퀘어", "금융"),
    MvpStock(5, "009150", "삼성전기", "전기전자"),
    MvpStock(6, "373220", "LG에너지솔루션", "전기전자"),
    MvpStock(7, "005380", "현대차", "운송장비·부품"),
    MvpStock(8, "207940", "삼성바이오로직스", "제약"),
    MvpStock(9, "105560", "KB금융", "금융"),
    MvpStock(10, "032830", "삼성생명", "보험"),
    MvpStock(11, "028260", "삼성물산", "유통"),
    MvpStock(12, "012450", "한화에어로스페이스", "운송장비·부품"),
    MvpStock(13, "034020", "두산에너빌리티", "기계·장비"),
    MvpStock(14, "055550", "신한지주", "금융"),
    MvpStock(15, "329180", "HD현대중공업", "운송장비·부품"),
    MvpStock(16, "000270", "기아", "운송장비·부품"),
    MvpStock(17, "006400", "삼성SDI", "전기전자"),
    MvpStock(18, "068270", "셀트리온", "제약"),
    MvpStock(19, "034730", "SK", "금융"),
    MvpStock(20, "086790", "하나금융지주", "금융"),
    MvpStock(21, "066570", "LG전자", "전기전자"),
    MvpStock(22, "012330", "현대모비스", "운송장비·부품"),
    MvpStock(23, "010120", "LS ELECTRIC", "전기전자"),
    MvpStock(24, "035420", "NAVER", "IT 서비스"),
    MvpStock(25, "000810", "삼성화재", "보험"),
    MvpStock(26, "298040", "효성중공업", "전기전자"),
    MvpStock(27, "042700", "한미반도체", "기계·장비"),
    MvpStock(28, "096770", "SK이노베이션", "화학"),
    MvpStock(29, "316140", "우리금융지주", "금융"),
    MvpStock(30, "005490", "POSCO홀딩스", "금속"),
)

MVP_CODES: frozenset[str] = frozenset(stock.code for stock in MVP_STOCKS)
