import pytest

from app.services import stock_detail

# 테스트용 종목은 MVP 고정 목록에 없다. 상세 API 가드(require_stock)를 통과하도록 더해 둔다.
TEST_STOCK_CODES = frozenset({"TST001"})


@pytest.fixture(autouse=True)
def allow_test_stocks(monkeypatch):
    monkeypatch.setattr(stock_detail, "MVP_CODES", stock_detail.MVP_CODES | TEST_STOCK_CODES)
