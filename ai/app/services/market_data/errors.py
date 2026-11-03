"""시장 데이터 예외. 호출하는 쪽은 MarketDataError 하나로 다 받을 수 있다.

**데이터가 없는 것은 예외가 아니다.** KRX 는 당일·휴장일을 빈 배열로 주고, ECOS 는 INFO-200 으로
알린다. 둘 다 빈 결과로 돌려준다. 여기 예외는 키가 틀렸거나 응답 모양이 기대와 다를 때만 난다.
"""


class MarketDataError(RuntimeError):
    pass


class KrxError(MarketDataError):
    pass


class KrxAuthError(KrxError):
    """401. 키가 틀렸거나, 키는 맞지만 그 API 의 이용신청이 안 됐다. 메시지가 둘을 가른다."""


class EcosError(MarketDataError):
    """ECOS 가 RESULT 로 알린 오류(INFO-200 제외)나 HTTP 실패. 메시지에 키는 들어가지 않는다."""


class ParseError(MarketDataError, ValueError):
    """숫자 칸에 숫자로 못 읽는 값이 왔다. 조용히 0 으로 바꾸면 틀린 등락률이 보고서에 실린다."""
