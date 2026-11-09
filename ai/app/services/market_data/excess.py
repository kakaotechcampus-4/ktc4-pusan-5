"""코스피 대비 초과 등락. 종목이 시장 때문에 움직였는지, 제 이유로 움직였는지 가르는 첫 숫자다.

    초과분(%p) = 종목 등락률(%) − 코스피 등락률(%)

코스피가 −2% 인 날 종목이 −1% 면 초과분은 +1%p 다. "떨어졌지만 시장보다 덜 떨어졌다" 는 뜻이다.
등락률끼리의 단순 차이다. 베타(시장 민감도)는 반영하지 않는다.

**체결이 없던 종목은 계산하지 않는다(None).** 거래정지 종목은 등락률이 "0.00" 으로 와서,
그대로 빼면 코스피 등락률을 뒤집은 값이 초과분이 된다(코스피 +1% 면 −1%p). 대형주도
액면분할·합병 때 거래정지가 생긴다.
"""

from app.services.market_data.schema import ExcessMove, IndexDaily, StockDaily

# KRX 등락률이 소수 둘째 자리라 차이도 둘째 자리면 정확하다. 반올림은 부동소수점 찌꺼기
# (0.24 - -0.25 = 0.49000000000000005)만 떼어낸다.
DECIMALS = 2


def excess_return(stock_rate: float, index_rate: float) -> float:
    """종목 등락률 − 지수 등락률 (%p)."""
    return round(stock_rate - index_rate, DECIMALS)


def compute_excess(stock: StockDaily, index: IndexDaily) -> ExcessMove | None:
    """같은 날의 종목·지수 행으로 초과분을 만든다.

    그날 체결이 없던 종목(거래량 0)은 None 이다. 날짜가 다르거나 등락률이 비어 있으면 멈춘다.
    """
    if stock.bas_dd != index.bas_dd:
        raise ValueError(f"기준일이 다르다: 종목 {stock.bas_dd}, 지수 {index.bas_dd}")
    if stock.no_trades:
        return None
    if stock.change_rate is None or index.change_rate is None:
        missing = stock.code if stock.change_rate is None else index.name
        raise ValueError(f"{stock.bas_dd} {missing} 의 등락률이 비어 있다")
    return ExcessMove(
        bas_dd=stock.bas_dd,
        code=stock.code,
        name=stock.name,
        stock_change_rate=stock.change_rate,
        index_change_rate=index.change_rate,
        excess_rate=excess_return(stock.change_rate, index.change_rate),
    )
