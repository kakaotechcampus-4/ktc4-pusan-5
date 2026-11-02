"""종목 변동 요인 보고서 조회 테스트. 리포지토리를 페이크로 갈아끼우므로 DB 없이 돈다."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from app.core.database import get_session
from app.main import app
from app.repositories.stock_report import (
    ReportRow,
    ReportStoreUnavailable,
    StockReportRepository,
    is_missing_table,
    latest_passed_statement,
)
from app.routers.stocks import get_report_repository
from app.services import stock_detail

KST = timezone(timedelta(hours=9))
QUOTE = "원문 인용 문장"

NEW_FORMAT = {
    "ticker": "TST001",
    "name": "테스트 종목",
    "date": "2026-09-18",
    "as_of": "15:30",
    "change_pct": -4.2,
    "verdict": "explained",
    "relative_verdict": "partially_explained",
    "summary": {
        "move": "장 마감 기준 4.2% 내렸습니다.",
        "main_cause": "3분기 영업이익이 예상보다 낮았습니다.",
        "relative": None,
        "counter": None,
        "unexplained": "해외 수요 영향은 확인되지 않았습니다.",
    },
    "factors": [
        {
            "event": "3분기 영업이익 예상치 하회",
            "detail": "",
            "stance": "bearish",
            "unconfirmed": False,
            "sources": [
                {
                    "channel": "sample_channel_a",
                    "url": "https://t.me/sample_channel_a/101",
                    "datetime_kst": "2026-09-18T08:10:00+09:00",
                    "quote": QUOTE,
                    "match": "direct",
                    "is_market_recap": False,
                }
            ],
            "links": [
                {
                    "layer": "move",
                    "note": "하락 방향과 맞습니다.",
                    "direction_match": True,
                    "strength": "sufficient",
                }
            ],
        }
    ],
    "terms": [{"plain": "다른 회사 칩을 대신 만들어 주는 사업", "term": "파운드리"}],
    "background": {
        "bullish": [],
        "bearish": [],
        "neutral": [{"text": "환율이 움직였습니다.", "sources": [], "watch": True}],
    },
    "not_found": ["검수용 메모"],
    "events": [{"event": "검수용 사건"}],
}

OLD_FORMAT_FACTOR = {
    "claim": "3분기 영업이익 예상치 하회",
    "detail": "",
    "stance": "bearish",
    "direction_match": True,
    "size_fit": "partial",
    "unconfirmed": False,
    "sources": [],
}


def make_row(raw_json, **overrides) -> ReportRow:
    values = {
        "id": 5530,
        "ticker": "TST001",
        "name": "테스트 종목",
        "target_date": date(2026, 9, 18),
        "as_of": datetime(2026, 9, 18, 15, 30, tzinfo=KST),
        "change_pct": -4.2,
        "generated_at": datetime(2026, 9, 18, 15, 41, tzinfo=KST),
        "loaded_at": datetime(2026, 9, 18, 15, 42, tzinfo=KST),
        "raw_json": raw_json,
    }
    values.update(overrides)
    return ReportRow(**values)


class FakeReportRepository:
    def __init__(self, row: ReportRow | None = None, error: Exception | None = None) -> None:
        self.row = row
        self.error = error
        self.codes: list[str] = []

    async def latest_passed(self, code: str) -> ReportRow | None:
        self.codes.append(code)
        if self.error:
            raise self.error
        return self.row


async def no_session():
    yield None


@pytest.fixture
def use_repository():
    app.dependency_overrides[get_session] = no_session

    def install(repository: FakeReportRepository) -> None:
        app.dependency_overrides[get_report_repository] = lambda: repository

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
def registered_stock(monkeypatch):
    async def exists(session, code):
        return None

    monkeypatch.setattr(stock_detail, "require_stock", exists)


async def get_report(code: str = "TST001"):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(f"/api/stocks/{code}/report")


async def test_ready_report_is_camel_case_and_hides_internal_fields(
    use_repository, registered_stock
):
    repository = FakeReportRepository(make_row(NEW_FORMAT))
    use_repository(repository)

    response = await get_report()

    assert response.status_code == 200
    body = response.json()
    assert repository.codes == ["TST001"]
    assert body["status"] == "ready"
    assert body["sourceAsOf"] == "2026-09-18T15:30:00+09:00"
    assert body["collectedAt"] == "2026-09-18T15:42:00+09:00"
    data = body["data"]
    assert data["id"] == 5530
    assert data["code"] == "TST001"
    assert data["asOf"] == "2026-09-18T15:30:00+09:00"
    assert data["generatedAt"] == "2026-09-18T15:41:00+09:00"
    assert data["changePct"] == -4.2
    assert data["verdict"] == "explained"
    assert data["relativeVerdict"] == "partially_explained"
    assert data["summary"]["mainCause"] == "3분기 영업이익이 예상보다 낮았습니다."
    assert data["summary"]["relative"] is None
    factor = data["factors"][0]
    assert factor["event"] == "3분기 영업이익 예상치 하회"
    assert factor["links"] == [
        {
            "layer": "move",
            "note": "하락 방향과 맞습니다.",
            "directionMatch": True,
            "strength": "sufficient",
        }
    ]
    assert factor["sources"][0]["url"] == "https://t.me/sample_channel_a/101"
    assert factor["sources"][0]["datetimeKst"] == "2026-09-18T08:10:00+09:00"
    assert factor["sources"][0]["isMarketRecap"] is False
    assert data["terms"] == [{"plain": "다른 회사 칩을 대신 만들어 주는 사업", "term": "파운드리"}]
    assert data["background"]["neutral"][0]["watch"] is True
    # 원문 인용과 검수용 칸은 내보내지 않는다.
    assert QUOTE not in response.text
    assert "quote" not in response.text
    assert "notFound" not in response.text and "not_found" not in response.text
    assert "events" not in data


async def test_old_format_factor_is_converted_to_links(use_repository, registered_stock):
    raw = {**NEW_FORMAT, "factors": [OLD_FORMAT_FACTOR]}
    raw.pop("relative_verdict")
    use_repository(FakeReportRepository(make_row(raw)))

    body = (await get_report()).json()

    assert body["status"] == "ready"
    factor = body["data"]["factors"][0]
    assert factor["event"] == "3분기 영업이익 예상치 하회"
    assert factor["links"] == [
        {"layer": "move", "note": None, "directionMatch": True, "strength": "partial"}
    ]
    assert body["data"]["relativeVerdict"] is None


async def test_raw_json_string_is_accepted(use_repository, registered_stock):
    use_repository(FakeReportRepository(make_row(json.dumps(NEW_FORMAT, ensure_ascii=False))))

    assert (await get_report()).json()["status"] == "ready"


async def test_missing_as_of_column_is_rebuilt_from_report(use_repository, registered_stock):
    use_repository(FakeReportRepository(make_row(NEW_FORMAT, as_of=None, target_date=None)))

    data = (await get_report()).json()["data"]

    assert data["asOf"] == "2026-09-18T15:30:00+09:00"


async def test_no_report_is_pending(use_repository, registered_stock):
    use_repository(FakeReportRepository(None))

    response = await get_report()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["data"] is None
    assert body["refreshing"] is False


async def test_missing_table_is_unavailable_not_server_error(use_repository, registered_stock):
    use_repository(FakeReportRepository(error=ReportStoreUnavailable("stock_move_analyses")))

    response = await get_report()

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["data"] is None


@pytest.mark.parametrize(
    "raw",
    [
        {**NEW_FORMAT, "verdict": "maybe"},
        {k: v for k, v in NEW_FORMAT.items() if k != "verdict"},
        {**NEW_FORMAT, "factors": [{"detail": "event 가 없다"}]},
        ["not", "an", "object"],
        "not json",
        None,
    ],
)
async def test_report_that_breaks_the_contract_is_unavailable(
    raw, use_repository, registered_stock
):
    use_repository(FakeReportRepository(make_row(raw)))

    body = (await get_report()).json()

    assert body["status"] == "unavailable"
    assert body["data"] is None


async def test_unregistered_stock_is_404_before_reading_reports(use_repository):
    repository = FakeReportRepository(make_row(NEW_FORMAT))
    use_repository(repository)

    response = await get_report("ZZZ999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STOCK_NOT_FOUND"
    assert repository.codes == []


def test_statement_reads_only_verified_latest_row():
    sql = str(
        latest_passed_statement("005930").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "FROM stock_move_analyses" in sql
    assert "ticker = '005930'" in sql
    assert "verify_status = 'passed'" in sql
    assert "parse_status = 'ok'" in sql
    assert "target_date DESC NULLS LAST" in sql
    assert "id DESC" in sql
    assert "LIMIT 1" in sql


def missing_table_error(message: str) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, Exception(message))


def test_missing_table_error_is_recognised():
    assert is_missing_table(missing_table_error('relation "stock_move_analyses" does not exist'))
    assert not is_missing_table(missing_table_error('relation "other" does not exist'))
    assert not is_missing_table(missing_table_error("connection refused"))


class FailingSession:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def execute(self, statement):
        raise self.error


async def test_repository_turns_missing_table_into_unavailable():
    session = FailingSession(missing_table_error('relation "stock_move_analyses" does not exist'))

    with pytest.raises(ReportStoreUnavailable):
        await StockReportRepository(session).latest_passed("TST001")


async def test_repository_does_not_hide_other_database_errors():
    error = missing_table_error("connection refused")

    with pytest.raises(DBAPIError):
        await StockReportRepository(FailingSession(error)).latest_passed("TST001")
