"""응답 문자열 → 숫자. **KRX·ECOS 응답의 숫자 변환은 전부 여기서만 한다.**

두 API 모두 숫자를 JSON 문자열로 준다(KRX `"-1.42"`, `"422276446"`, ECOS `"1385.2"`).
가공은 하지 않는다. 단위도 바꾸지 않는다 — 원은 원, %는 % 그대로다.

값이 없는 칸은 None 이다. KRX 지수 응답의 "코스피 (외국주포함)" 행은 가격 칸이 `""` 로 온다.
"""

from app.services.market_data.errors import ParseError

# 값이 없다는 뜻으로 오는 문자열. 0 으로 읽으면 "보합" 과 구분이 안 된다.
_BLANKS = {"", "-"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("−", "-")  # 유니코드 마이너스(−)
    return None if text in _BLANKS else text


def to_float(value: str | None, *, field: str = "") -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        raise ParseError(f"{field or '값'} 을 숫자로 못 읽음: {value!r}") from None


def to_int(value: str | None, *, field: str = "") -> int | None:
    """정수 칸(주가·거래량·거래대금·시가총액). 소수점이 붙어 오면 잘라내지 않고 멈춘다."""
    text = _clean(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        raise ParseError(f"{field or '값'} 을 정수로 못 읽음: {value!r}") from None
