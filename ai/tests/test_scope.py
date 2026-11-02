"""수집 범위(collection_scope.toml). 범위를 정하지 않았거나 잘못 적었으면 수집하지 않는다."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.scope import DEFAULT_PATH, ScopeError, load_scope, parse_scope

KST = timezone(timedelta(hours=9))
TERMS = {"status": "미확인"}


def scope(**sources):
    return parse_scope({
        "period": {"start": date(2026, 10, 6), "end": date(2026, 10, 31)},
        "sources": sources,
    })


def web(**values):
    return {"enabled": True, "channels": ["skitteam"], "max_items": 100, "terms": TERMS, **values}


def test_committed_scope_file_collects_nothing_until_the_team_fills_it():
    """저장소의 기본 범위 파일은 모든 출처가 꺼져 있다. 그대로 두면 어떤 수집기도 돌지 않는다."""
    committed = load_scope(DEFAULT_PATH)
    assert committed.sources and not any(s.enabled for s in committed.sources.values())
    with pytest.raises(ScopeError, match="꺼져 있다"):
        committed.require("telegram_web")


def test_missing_file_is_an_error_not_an_empty_scope(tmp_path):
    with pytest.raises(ScopeError, match="수집 범위 파일이 없다"):
        load_scope(tmp_path / "none.toml")


def test_enabled_source_must_have_period_list_limit_and_terms():
    with pytest.raises(ScopeError) as error:
        parse_scope({"sources": {"telegram_web": {"enabled": True}}})
    message = str(error.value)
    for missing in ("period", "max_items", "channels", "terms"):
        assert missing in message


def test_terms_status_must_be_recorded_even_when_unchecked():
    with pytest.raises(ScopeError, match="status"):
        scope(telegram_web=web(terms={"status": "모름"}))
    recorded = scope(telegram_web=web(terms={
        "status": "미확정", "basis": "채널 공지", "checked_on": date(2026, 10, 5),
        "open_issues": ["재전달 기사는 별도 확인"],
    }))
    assert recorded.source("telegram_web").terms.open_issues == ("재전달 기사는 별도 확인",)


def test_company_reports_need_stock_codes():
    research = {"enabled": True, "categories": ["company"], "max_items": 10, "terms": TERMS}
    with pytest.raises(ScopeError, match="item_codes"):
        scope(naver_research=research)
    assert scope(naver_research={**research, "item_codes": ["005930"]}).source(
        "naver_research").item_codes == {"005930"}


def test_typos_are_rejected_instead_of_silently_ignored():
    with pytest.raises(ScopeError, match="모르는 출처"):
        scope(telegram=web())
    with pytest.raises(ScopeError, match="모르는 항목"):
        scope(telegram_web=web(channel=["skitteam"]))


def test_check_and_remaining():
    source = scope(telegram_web=web(max_items=10)).require("telegram_web")
    source.check(["skitteam"])
    with pytest.raises(ScopeError, match="merITz_tech"):
        source.check(["skitteam", "merITz_tech"])
    assert (source.remaining(3), source.remaining(10), source.remaining(12)) == (7, 0, 0)


def test_period_is_inclusive_and_clips_collection_windows():
    s = scope()
    assert s.contains(date(2026, 10, 6)) and s.contains(date(2026, 10, 31))
    assert not s.contains(date(2026, 11, 1))
    assert s.first_day(date(2026, 10, 1)) == date(2026, 10, 6)
    assert s.first_day(date(2026, 11, 2)) is None

    lo, hi = s.window(datetime(2026, 10, 1, tzinfo=KST), datetime(2026, 11, 3, 9, tzinfo=KST))
    assert lo == datetime(2026, 10, 6, tzinfo=KST)
    assert hi.date() == date(2026, 10, 31) and hi.hour == 23
    assert s.window(datetime(2026, 11, 2, tzinfo=KST), datetime(2026, 11, 3, tzinfo=KST)) is None
