import pytest
from pydantic import ValidationError

from app.core.config import Settings

_JWT = "x" * 32


def _make(**kwargs) -> Settings:
    # .env 의 값이 섞이지 않도록 파일을 읽지 않고 필요한 값만 직접 넘긴다
    return Settings(_env_file=None, jwt_secret_key=_JWT, **kwargs)


def test_app_env_defaults_to_production():
    assert _make().app_env == "production"


def test_test_login_rejected_in_production():
    with pytest.raises(ValidationError, match="APP_ENV=local"):
        _make(app_env="production", enable_test_login=True)


def test_test_login_rejected_when_app_env_unset():
    # APP_ENV 를 안 넣으면 production 이므로 켤 수 없다
    with pytest.raises(ValidationError):
        _make(enable_test_login=True)


def test_test_login_allowed_in_local():
    s = _make(app_env="local", enable_test_login=True)
    assert s.enable_test_login is True


def test_test_login_off_is_fine_in_production():
    assert _make(app_env="production", enable_test_login=False).enable_test_login is False
