"""dart_disclosures 저장 규칙을 실제 PostgreSQL 에서 본다.

    - 같은 접수번호는 한 행이고, 다시 받아도 처음 본 시각(first_seen_at)이 바뀌지 않는다
    - 행이 있으면 downgrade 가 표를 지우지 않는다
"""

from datetime import date

from app.repositories.dart_disclosure import known_rcept_nos, save_disclosures
from app.repositories.scope import count_collected
from app.services.dart.schema import Disclosure
from tests.db import in_session
from tests.test_migrations import alembic, query


def item(rcept_no: str = "20261008000123", **values) -> Disclosure:
    return Disclosure(**{
        "rcept_no": rcept_no, "corp_code": "00126380", "corp_name": "삼성전자",
        "stock_code": "005930", "report_nm": "주요사항보고서(자기주식취득결정)",
        "flr_nm": "삼성전자", "rcept_dt": date(2026, 10, 8), "rm": "유", **values,
    })


def save(database: str, items: list[Disclosure]) -> int:
    return in_session(database, lambda session: save_disclosures(session, items))


def test_same_disclosure_is_one_row_and_keeps_first_seen_at(database):
    alembic(database, "upgrade", "head")
    assert save(database, [item()]) == 1
    [first] = query(database, "SELECT first_seen_at FROM dart_disclosures")

    assert save(database, [item(report_nm="바뀐 제목"), item("20261008000124")]) == 1
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
