"""시장 데이터 — KRX(코스피 지수·유가증권 종목 일별) 와 ECOS(원/달러 환율·기준금리).

    from app.services.market_data import compute_excess, fetch_kospi, fetch_stock

    kospi = await fetch_kospi(client, day)
    stock = await fetch_stock(client, day, "005930")
    if kospi and stock:
        move = compute_excess(stock, kospi)  # move.excess_rate: 코스피 대비 초과분(%p)
        # 그날 체결이 없던 종목(거래정지)이면 move 는 None 이다

시장 맥락(코스피 비중·기여도·자기 제외 코스피, 동종 그룹 비교)은 context.py 가 계산한다.

    ctx = await fetch_market_context(client, "005930", day)

동종 그룹 정의는 peer_groups.py 한 곳에 있다. 실험용 출력은 `python -m app.services.market_data`.

보고서 에이전트가 쓸 시장 정보를 읽기만 한다. DB 저장과 러너 연결은 아직 없다.
키는 app.core.config 의 KRX_AUTH_KEY·ECOS_API_KEY 에서 읽는다(require_krx·require_ecos).
숫자 변환은 parse.py 한 곳에서만 한다. 단위는 API 가 준 그대로다.
"""

from app.services.market_data.context import build_market_context, fetch_market_context
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
from app.services.market_data.peer_groups import GROUPS, STOCK_GROUPS, groups_of
from app.services.market_data.schema import (
    EcosPoint,
    ExcessMove,
    IndexDaily,
    KospiComparison,
    MarketContext,
    PeerComparison,
    PeerExclusion,
    StockDaily,
)

__all__ = [
    "BASE_RATE",
    "GROUPS",
    "STOCK_GROUPS",
    "USD_KRW",
    "EcosError",
    "EcosPoint",
    "EcosSeries",
    "ExcessMove",
    "IndexDaily",
    "KospiComparison",
    "KrxAuthError",
    "KrxError",
    "MarketContext",
    "MarketDataError",
    "ParseError",
    "PeerComparison",
    "PeerExclusion",
    "StockDaily",
    "build_market_context",
    "compute_excess",
    "excess_return",
    "fetch_base_rate",
    "fetch_kospi",
    "fetch_kospi_index_daily",
    "fetch_market_context",
    "fetch_series",
    "fetch_stock",
    "fetch_stock_daily",
    "fetch_usd_krw",
    "groups_of",
    "mask_key",
]
