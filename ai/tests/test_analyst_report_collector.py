"""네이버 리서치 수집기의 수집 범위. 네이버에 접속하지 않고 목록·상세를 가짜로 둔다.

범위 밖의 리포트는 상세·PDF 를 받지 않는다. 받고 나서 버리면 이미 수집한 것이다.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.collectors import analyst_report as collector
from app.core.scope import ScopeError, parse_scope
from app.services.analyst.schema import AnalystReportItem

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()


def scope(**research):
    return parse_scope({
        "period": {"start": TODAY - timedelta(days=30), "end": TODAY},
        "sources": {"naver_research": {
            "enabled": True, "categories": ["company", "industry"], "item_codes": ["005930"],
            "max_items": 3, "terms": {"status": "미확인"}, **research,
        }},
    })


def item(source_id, *, category="company", item_code="005930", write_date=TODAY):
    return AnalystReportItem(source_id=source_id, source_category=category, category=category,
                             title="리포트", broker="증권사", write_date=write_date,
                             item_code=item_code)


class FakeNaver:
    """NaverResearchClient 대신. 상세를 받은(enrich) 리포트 번호를 모은다."""

    def __init__(self, lists):
        self.lists = lists
        self.enriched: list[str] = []
        self.since = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def collect_since(self, category, since, *, known_ids=None):
        self.since = since
        return list(self.lists.get(category, []))

    async def enrich(self, items, *, with_pdf=True):
        self.enriched += [i.source_id for i in items]
        return [(i, None) for i in items]


@pytest.fixture
def db(monkeypatch):
    """DB 대신. 저장한 수만큼 쌓인 수(count_collected)가 늘어난다."""
    state = {"collected": 0}

    def save(session, rows):
        state["collected"] += len(rows)
        return len(rows)

    monkeypatch.setattr(collector, "SessionLocal", lambda: AsyncMock())
    monkeypatch.setattr(collector, "known_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(collector, "upsert_analyst_reports", AsyncMock(side_effect=save))
    monkeypatch.setattr(collector, "register_missing_sources", AsyncMock(return_value={}))
    monkeypatch.setattr(collector, "count_collected",
                        AsyncMock(side_effect=lambda session, source: state["collected"]))
    return state


async def test_only_allowed_stocks_dates_and_volume_are_fetched(monkeypatch, db):
    naver = FakeNaver({
        "company": [
            item("1"),
            item("2", item_code="000660"),  # 범위에 없는 종목
            item("3", write_date=TODAY - timedelta(days=60)),  # 기간 밖
            item("4"),
        ],
        "industry": [item("5", category="industry", item_code=None),
                     item("6", category="industry", item_code=None)],
    })
    monkeypatch.setattr(collector, "NaverResearchClient", lambda: naver)

    saved = await collector.collect(days=60, scope=scope())

    assert saved == {"company": 2, "industry": 1}, "상한 3 에서 company 2건 뒤에 1건만 남았다"
    assert naver.enriched == ["1", "4", "5"]
    assert naver.since == TODAY - timedelta(days=30), "목록도 기간 시작부터만 넘긴다"


async def test_category_outside_the_scope_is_refused_before_connecting(monkeypatch, db):
    monkeypatch.setattr(collector, "NaverResearchClient", lambda: pytest.fail("접속했다"))
    with pytest.raises(ScopeError, match="economy"):
        await collector.collect(categories=("economy",), scope=scope())


async def test_ended_period_collects_nothing(monkeypatch, db):
    monkeypatch.setattr(collector, "NaverResearchClient", lambda: pytest.fail("접속했다"))
    ended = parse_scope({
        "period": {"start": TODAY - timedelta(days=40), "end": TODAY - timedelta(days=20)},
        "sources": {"naver_research": {
            "enabled": True, "categories": ["industry"], "max_items": 3,
            "terms": {"status": "미확인"},
        }},
    })
    with pytest.raises(ScopeError, match="기간"):
        await collector.collect(days=7, scope=ended)
