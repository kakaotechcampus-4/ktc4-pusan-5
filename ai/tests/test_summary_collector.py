"""배치의 검증 실패 차단, 중복 재사용, 기존 결과 보존을 검증한다."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Update

from app.collectors import summary as collector
from app.models import AnalystReport

SUMMARY = "\n".join(
    f"{word} 시장의 흐름을 살피면서 공급과 수요의 변화를 함께 확인할 필요가 있다."
    for word in ("첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째", "여덟째", "아홉째", "열째")
)
BODY = "산업 전반의 수요와 공급을 분석한다. " * 150


@pytest.fixture(autouse=True)
def no_external_model_calls(monkeypatch):
    monkeypatch.setattr(collector, "generate", AsyncMock(side_effect=AssertionError("모델 호출 금지")))


def row(id=1, summary=None, sha="same-pdf", source="telegram", body=BODY):
    return AnalystReport(id=id, source=source, source_category="channel", source_id=str(id),
                         category="industry", title="산업_전망", write_date=date(2026, 9, 14),
                         body_text=body, body_chars=len(body), pdf_sha256=sha,
                         summary_text=summary)


def test_plan_reuses_valid_duplicate_without_overwriting_it():
    targets = collector.plan([row(1, SUMMARY), row(2), row(3, "")])
    assert len(targets) == 1
    assert targets[0].previous == {2: None, 3: ""}
    assert targets[0].reuse == SUMMARY


def test_repair_selects_invalid_only_and_force_includes_valid():
    rows = [row(1, SUMMARY), row(2, "짧은 실패 요약")]
    assert collector.plan(rows) == []
    repaired = collector.plan(rows, repair_invalid=True)
    assert repaired[0].previous == {2: "짧은 실패 요약"}
    forced = collector.plan(rows, force=True)
    assert set(forced[0].previous) == {1, 2}
    assert forced[0].reuse is None


def test_plan_excludes_naver_and_unusable_body_and_does_not_group_null_hashes():
    targets = collector.plan([row(1, sha=None), row(2, sha=None),
                              row(3, source="naver"), row(4, body="표지")])
    assert len(targets) == 2
    assert {t.report.id for t in targets} == {1, 2}


@pytest.mark.parametrize("limit", [0, -1])
def test_plan_rejects_nonpositive_limit(limit):
    with pytest.raises(ValueError):
        collector.plan([row()], limit=limit)


def setup_session(monkeypatch, rows, rowcount=1):
    session = AsyncMock()
    selected = MagicMock()
    selected.scalars.return_value.all.return_value = rows
    session.execute.side_effect = [selected] + [SimpleNamespace(rowcount=rowcount)] * 5
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    monkeypatch.setattr(collector, "SessionLocal", lambda: manager)
    return session


async def test_invalid_nonempty_generation_never_updates_database(monkeypatch):
    session = setup_session(monkeypatch, [row(summary="이전 요약")])
    generate = AsyncMock(return_value=("검증 실패 요약", {},
                                     {"ok": False, "problems": ["본문에 없는 숫자"]}))
    monkeypatch.setattr(collector, "generate", generate)
    result = await collector.run(repair_invalid=True)
    assert result["saved"] == 0 and result["failed"] == 1
    assert result["failures"][0]["ids"] == [1]
    assert session.execute.await_count == 1  # 최초 SELECT만 실행


async def test_reuse_updates_only_missing_row_and_checks_previous_value(monkeypatch):
    session = setup_session(monkeypatch, [row(1, SUMMARY), row(2)])
    generate = AsyncMock()
    monkeypatch.setattr(collector, "generate", generate)
    result = await collector.run()
    generate.assert_not_awaited()
    assert result["reused"] == 1 and result["saved_rows"] == 1
    stmt = session.execute.await_args_list[1].args[0]
    assert isinstance(stmt, Update)
    compiled = stmt.compile()
    assert compiled.params["id_1"] == 2
    assert "summary_text IS NULL" in str(compiled)
    assert "body_text IS NOT DISTINCT FROM" in str(compiled)
    assert "pdf_sha256 IS NOT DISTINCT FROM" in str(compiled)
    assert compiled.params["summary_text"] == SUMMARY


async def test_concurrent_edit_is_reported_as_conflict(monkeypatch):
    setup_session(monkeypatch, [row(1, SUMMARY), row(2)], rowcount=0)
    result = await collector.run()
    assert result["saved"] == 0 and result["conflicts"] == 1


async def test_dry_run_never_creates_tables_or_calls_model(monkeypatch):
    session = setup_session(monkeypatch, [row()])
    generate = AsyncMock()
    monkeypatch.setattr(collector, "generate", generate)
    result = await collector.run(dry_run=True)
    generate.assert_not_awaited()
    assert session.execute.await_count == 1
    assert result["targets"] == 1 and result["saved"] == 0


async def test_explicit_report_ids_scope_database_selection(monkeypatch):
    session = setup_session(monkeypatch, [row(503)])
    await collector.run(dry_run=True, report_ids=[503])
    stmt = session.execute.await_args.args[0]
    assert stmt.compile().params["id_1"] == [503]
