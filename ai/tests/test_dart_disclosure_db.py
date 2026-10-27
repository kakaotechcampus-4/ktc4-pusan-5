"""dart_disclosures 저장 규칙과 공통 자료 ID 연결을 실제 PostgreSQL 에서 본다.

    - 같은 접수번호는 한 행이고, 다시 받아도 처음 본 시각(first_seen_at)이 바뀌지 않는다
    - 행이 있으면 downgrade 가 표를 지우지 않는다
    - 공시도 카드 하나를 받고, 공개 시각·접수일·종목이 적힌다
    - 공시를 가리키는 카드가 있으면 0026 downgrade 가 멈춘다
"""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.repositories.dart_disclosure import known_rcept_nos, save_disclosures
from app.repositories.scope import count_collected
from app.repositories.source_card import (
    _dart_rcept_no,
    card_ids_for_urls,
    get_sources,
    register_missing_sources,
    stock_card_ids,
)
from app.services.dart.schema import Disclosure
from tests.db import in_session
from tests.test_migrations import alembic, columns, query

KST = timezone(timedelta(hours=9))


def item(rcept_no: str = "20261008000123", **values) -> Disclosure:
    return Disclosure(**{
        "rcept_no": rcept_no, "corp_code": "00126380", "corp_name": "삼성전자",
        "stock_code": "005930", "report_nm": "주요사항보고서(자기주식취득결정)",
        "flr_nm": "삼성전자", "rcept_dt": date(2026, 10, 8), "rm": "유", **values,
    })


def save(database: str, items: list[Disclosure]) -> list[int]:
    return in_session(database, lambda session: save_disclosures(session, items))


def register(database: str) -> dict[str, int]:
    return in_session(database, register_missing_sources)


def test_same_disclosure_is_one_row_and_keeps_first_seen_at(database):
    alembic(database, "upgrade", "head")
    assert len(save(database, [item()])) == 1
    [first] = query(database, "SELECT first_seen_at FROM dart_disclosures")

    assert len(save(database, [item(report_nm="바뀐 제목"), item("20261008000124")])) == 1
    rows = query(database, "SELECT * FROM dart_disclosures ORDER BY rcept_no")
    assert [r["rcept_no"] for r in rows] == ["20261008000123", "20261008000124"]
    assert rows[0]["report_nm"] == "주요사항보고서(자기주식취득결정)"
    assert rows[0]["first_seen_at"] == first["first_seen_at"]

    assert in_session(database, lambda s: known_rcept_nos(s, ["20261008000123", "x"])) == {
        "20261008000123"}
    assert in_session(database, lambda s: count_collected(s, "dart")) == 2


def test_downgrade_refuses_while_disclosures_are_stored(database):
    alembic(database, "upgrade", "head")
    save(database, [item()])
    out = alembic(database, "downgrade", "0024_source_card_stocks", success=False)
    assert "dart_disclosures" in out
    query(database, "DELETE FROM dart_disclosures")
    alembic(database, "downgrade", "0024_source_card_stocks")
    assert not query(database, "SELECT 1 FROM information_schema.tables "
                               "WHERE table_name = 'dart_disclosures'")


def seed_two_days(database: str) -> None:
    """접수일 안에 본 공시 하나(10-08 16:10 KST)와, 지난 날짜(10-06)를 10-08 에 받은 공시 하나."""
    save(database, [item("20261008000123"),
                    item("20261006000045", rcept_dt=date(2026, 10, 6), report_nm="기업설명회")])
    query(database, "UPDATE dart_disclosures SET first_seen_at = '2026-10-08 16:10+09'")


def test_disclosure_card_gets_public_time_date_and_stock(database):
    alembic(database, "upgrade", "head")
    seed_two_days(database)

    assert register(database) == {"news": 0, "pdf": 0, "message": 0, "disclosure": 2}
    assert register(database) == {"news": 0, "pdf": 0, "message": 0, "disclosure": 0}

    rows = query(database, """
        SELECT d.rcept_no, c.card_type, c.source_name, c.available_at, c.event_date::text AS day,
               c.raw_text
        FROM source_card c JOIN dart_disclosures d ON d.id = c.dart_disclosure_id
        ORDER BY d.rcept_no
    """)
    assert [tuple(r) for r in rows] == [
        # 지난 날짜를 나중에 받았다: 처음 본 시각은 실제 공시보다 늦으므로 쓰지 않고 접수일만
        ("20261006000045", "disclosure", "삼성전자", None, "2026-10-06", None),
        ("20261008000123", "disclosure", "삼성전자",
         datetime(2026, 10, 8, 7, 10, tzinfo=UTC), "2026-10-08", None),
    ]
    tags = query(database, "SELECT stock_code, tagged_by FROM source_card_stocks")
    assert [tuple(t) for t in tags] == [("005930", "dart_stock_code")] * 2

    def find(until):
        return in_session(database, lambda s: stock_card_ids(s, "005930", until=until))

    old, today = (r[0] for r in query(database, """
        SELECT c.id FROM source_card c JOIN dart_disclosures d ON d.id = c.dart_disclosure_id
        ORDER BY d.rcept_no
    """))
    # 10-08 15:00: 10-06 공시만. 10-08 공시는 16:10 에 처음 봤다
    assert find(datetime(2026, 10, 8, 15, 0, tzinfo=KST)) == [old]
    assert find(datetime(2026, 10, 8, 17, 0, tzinfo=KST)) == [old, today]


def test_disclosure_card_reads_back_and_matches_its_viewer_url(database):
    alembic(database, "upgrade", "head")
    seed_two_days(database)
    register(database)
    [card_id] = query(database, """
        SELECT c.id FROM source_card c JOIN dart_disclosures d ON d.id = c.dart_disclosure_id
        WHERE d.rcept_no = '20261008000123'
    """)[0]

    [record] = in_session(database, lambda s: get_sources(s, [card_id], include_body=True))
    assert (record.kind, record.title, record.publisher, record.collection_path) == (
        "disclosure", "주요사항보고서(자기주식취득결정)", "삼성전자", "dart_list")
    assert record.url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261008000123"
    assert record.write_date == date(2026, 10, 8)
    assert not record.has_body and record.body is None
    assert record.body_missing_reason.startswith("not_collected")

    found = in_session(database, lambda s: card_ids_for_urls(s, [
        record.url,
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261008999999",  # DB 에 없다
        "https://example.com/?rcpNo=20261008000123",  # DART 주소가 아니다
    ]))
    assert found == {record.url: card_id}


def test_source_card_downgrade_refuses_while_cards_point_to_disclosures(database):
    alembic(database, "upgrade", "head")
    save(database, [item()])
    register(database)
    out = alembic(database, "downgrade", "0025_dart_disclosures", success=False)
    assert "dart_disclosures" in out
    assert "dart_disclosure_id" in columns(database, "source_card"), "아무것도 바꾸지 않았다"

    query(database, "DELETE FROM source_card WHERE card_type = 'disclosure'")
    alembic(database, "downgrade", "0025_dart_disclosures")
    assert "dart_disclosure_id" not in columns(database, "source_card")


@pytest.mark.parametrize("mock_url,expected", [
    ("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261008000123", "20261008000123"),
    ("http://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261008000123&foo=1", "20261008000123"),
    ("https://notdart.fss.or.kr/dsaf001/main.do?rcpNo=20261008000123", None),
    ("https://dart.fss.or.kr.example.com/dsaf001/main.do?rcpNo=20261008000123", None),
    ("https://dart.fss.or.kr/other?rcpNo=20261008000123", None),
    ("ftp://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261008000123", None),
    ("https://dart.fss.or.kr/dsaf001/main.do", None),
    ("https://[invalid", None),
])
def test_dart_viewer_url_validation(mock_url, expected):
    assert _dart_rcept_no(mock_url) == expected


@pytest.mark.parametrize("mock_registration_fails", [False, True])
async def test_collector_commits_disclosures_before_registering_cards(monkeypatch,
                                                                    mock_registration_fails):
    from app.collectors import disclosure as collector
    from tests.test_dart import DAY, scope

    mock_save_session = AsyncMock()
    mock_card_session = AsyncMock()
    mock_sessions = iter([mock_save_session, mock_card_session])

    @asynccontextmanager
    async def mock_session_factory():
        yield next(mock_sessions)

    @asynccontextmanager
    async def mock_locks(*args):
        yield

    async def mock_register(session, **kwargs):
        mock_save_session.commit.assert_awaited_once()
        assert session is mock_card_session
        assert kwargs == {
            "news_ids": [], "report_ids": [], "message_ids": [], "disclosure_ids": [42],
        }
        if mock_registration_fails:
            raise RuntimeError("mock registration failure")
        return {"news": 0, "pdf": 0, "message": 0, "disclosure": 1}

    monkeypatch.setattr(collector, "SessionLocal", mock_session_factory)
    monkeypatch.setattr(collector, "collection_locks", mock_locks)
    monkeypatch.setattr(collector.dart, "fetch_day", AsyncMock(return_value=[item()]))
    monkeypatch.setattr(collector, "known_rcept_nos", AsyncMock(return_value=set()))
    monkeypatch.setattr(collector, "count_collected", AsyncMock(return_value=0))
    monkeypatch.setattr(collector, "save_disclosures", AsyncMock(return_value=[42]))
    monkeypatch.setattr(collector, "register_missing_sources", mock_register)

    result = await collector.collect(DAY, scope=scope())
    assert result.inserted == 1
    if mock_registration_fails:
        assert result.register_error == "RuntimeError: mock registration failure"
        mock_card_session.commit.assert_not_awaited()
    else:
        assert result.register_error is None
        assert result.cards["disclosure"] == 1
        mock_card_session.commit.assert_awaited_once()
