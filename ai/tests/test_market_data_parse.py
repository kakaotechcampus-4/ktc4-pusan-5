"""시장 데이터 숫자 변환. KRX·ECOS 는 숫자를 문자열로 준다."""

import pytest

from app.core.config import Settings
from app.services.market_data import ParseError
from app.services.market_data.parse import to_float, to_int


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-1.42", -1.42),
        ("1.89", 1.89),  # 상승은 부호 없이 온다
        ("−1.08", -1.08),  # 유니코드 마이너스
        ("1,391.2", 1391.2),
        (" 7033.92 ", 7033.92),
        ("0", 0.0),
    ],
)
def test_to_float_reads_api_strings(raw: str, expected: float) -> None:
    assert to_float(raw) == expected


@pytest.mark.parametrize("raw", ["", "-", None, "  "])
def test_blank_is_none_not_zero(raw: str | None) -> None:
    # 0 은 보합이다. 비어 있는 칸을 0 으로 읽으면 "안 움직였다" 가 된다
    assert to_float(raw) is None
    assert to_int(raw) is None


def test_to_int_reads_big_numbers() -> None:
    assert to_int("5802329384905229") == 5802329384905229
    assert to_int("-680") == -680
    assert to_int("62,400") == 62400


def test_unreadable_value_stops_with_field_name() -> None:
    with pytest.raises(ParseError, match="FLUC_RT"):
        to_float("N/A", field="FLUC_RT")
    # 정수 칸에 소수가 오면 잘라내지 않는다
    with pytest.raises(ParseError, match="TDD_CLSPRC"):
        to_int("4180.5", field="TDD_CLSPRC")


@pytest.mark.parametrize(
    ("method", "env_name"),
    [("require_krx", "KRX_AUTH_KEY"), ("require_ecos", "ECOS_API_KEY")],
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_names_the_key(method: str, env_name: str, value: str | None) -> None:
    # .env.example 그대로 `KRX_AUTH_KEY=` 로 비워 둔 경우도 없는 것과 같다
    settings = Settings(_env_file=None, krx_auth_key=value, ecos_api_key=value)
    with pytest.raises(RuntimeError, match=env_name):
        getattr(settings, method)()


def test_present_key_is_returned_stripped() -> None:
    settings = Settings(_env_file=None, krx_auth_key=" krx-key ", ecos_api_key="ecos-key")
    assert settings.require_krx() == "krx-key"
    assert settings.require_ecos() == "ecos-key"
