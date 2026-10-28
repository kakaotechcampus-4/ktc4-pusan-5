"""시장 데이터 — KRX(코스피 지수·유가증권 종목 일별) 와 ECOS(원/달러 환율·기준금리).

    from app.services.market_data import compute_excess, fetch_kospi, fetch_stock

    kospi = await fetch_kospi(client, day)
    stock = await fetch_stock(client, day, "005930")
    if kospi and stock:
        move = compute_excess(stock, kospi)  # move.excess_rate: 코스피 대비 초과분(%p)

보고서 에이전트가 쓸 시장 정보를 읽기만 한다. DB 저장과 러너 연결은 아직 없다.
키는 app.core.config 의 KRX_AUTH_KEY·ECOS_API_KEY 에서 읽는다(require_krx·require_ecos).
숫자 변환은 parse.py 한 곳에서만 한다. 단위는 API 가 준 그대로다.
"""

from app.services.market_data.ecos import (
    BASE_RATE,
    USD_KRW,
    EcosSeries,
    fetch_base_rate,
    fetch_series,
    fetch_usd_krw,
    mask_key,
)
from app.services.market_data.errors import (
    EcosError,
    KrxAuthError,
    KrxError,
    MarketDataError,
    ParseError,
)
from app.services.market_data.excess import compute_excess, excess_return
from app.services.market_data.krx import (
    fetch_kospi,
    fetch_kospi_index_daily,
    fetch_stock,
    fetch_stock_daily,
)
from app.services.market_data.schema import EcosPoint, ExcessMove, IndexDaily, StockDaily

__all__ = [
    "BASE_RATE",
    "USD_KRW",
    "EcosError",
    "EcosPoint",
    "EcosSeries",
    "ExcessMove",
    "IndexDaily",
    "KrxAuthError",
    "KrxError",
    "MarketDataError",
    "ParseError",
    "StockDaily",
    "compute_excess",
    "excess_return",
    "fetch_base_rate",
    "fetch_kospi",
    "fetch_kospi_index_daily",
    "fetch_series",
    "fetch_stock",
    "fetch_stock_daily",
    "fetch_usd_krw",
    "mask_key",
]
