import os

# backend/.env 에 진짜 SENTRY_DSN 이 있어도 테스트는 Sentry 로 보내지 않는다.
# 설정을 읽기 전에 비워 둔다(pydantic-settings 는 .env 보다 환경변수를 먼저 본다).
os.environ["SENTRY_DSN"] = ""

import pytest

from app.services import stock_detail

# 테스트용 종목은 MVP 고정 목록에 없다. 상세 API 가드(require_stock)를 통과하도록 더해 둔다.
TEST_STOCK_CODES = frozenset({"TST001"})


@pytest.fixture(autouse=True)
def allow_test_stocks(monkeypatch):
    monkeypatch.setattr(stock_detail, "MVP_CODES", stock_detail.MVP_CODES | TEST_STOCK_CODES)
