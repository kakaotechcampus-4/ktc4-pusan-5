"""라우터 테스트. 리포지토리를 페이크로 갈아끼우므로 DB 없이 돈다."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import Concept
from app.routers.concepts import get_repository

KST = timezone(timedelta(hours=9))

TREASURY = Concept(
    slug="treasury-stock",
    name="자사주",
    aliases=["자기주식"],
    category="shareholder-return/treasury-stock",
    extra_categories=None,
    summary="회사가 자기 회사 주식을 다시 사들인 것.",
    body="[배당](dividend) 과 비교해 보세요.",
    related=[
        {"slug": "dividend", "reason": "현금으로 돌려주는 다른 방식"},
        {"slug": "ghost", "reason": "DB 에 없는 개념"},
    ],
    quiz=[{"question": "질문", "answer": True, "explanation": "해설"}],
    sources=[],
    generated_at=None,
    updated_at=datetime(2026, 8, 21, 15, 30, tzinfo=KST),
)

DIVIDEND = Concept(
    slug="dividend",
    name="배당",
    aliases=[],
    category="shareholder-return/dividend",
    extra_categories=["macro/interest-rate"],
    summary="이익의 일부를 나눠주는 것.",
    body="본문",
    related=None,
    quiz=None,
    sources=[],
    generated_at=None,
    updated_at=datetime(2026, 8, 21, 15, 30, tzinfo=KST),
)


class FakeConceptRepository:
    def __init__(self, concepts: list[Concept]) -> None:
        self.by_slug = {concept.slug: concept for concept in concepts}

    async def list_all(self) -> list[Concept]:
        return sorted(self.by_slug.values(), key=lambda concept: concept.slug)

    async def get_by_slug(self, slug: str) -> Concept | None:
        return self.by_slug.get(slug)

    async def get_names_by_slugs(self, slugs: list[str]) -> dict[str, str]:
        return {slug: self.by_slug[slug].name for slug in slugs if slug in self.by_slug}


@pytest.fixture
async def client():
    app.dependency_overrides[get_repository] = lambda: FakeConceptRepository([TREASURY, DIVIDEND])
    transport = ASGITransport(app=app)  # lifespan 을 타지 않으므로 DB 에 붙지 않는다
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


async def test_list_returns_items_sorted_by_slug_with_joined_category(client):
    response = await client.get("/api/concepts")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["slug"] for item in items] == ["dividend", "treasury-stock"]
    assert items[0]["category"] == {
        "domain": {"slug": "shareholder-return", "name": "주주환원"},
        "subdomain": {"slug": "dividend", "name": "배당"},
    }
    assert set(items[0]) == {"slug", "name", "aliases", "summary", "category"}


async def test_detail_uses_camel_case_keys_and_joins_related_names(client):
    response = await client.get("/api/concepts/treasury-stock")
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {
        "slug",
        "name",
        "aliases",
        "category",
        "extraCategories",
        "summary",
        "body",
        "related",
        "quiz",
        "updatedAt",
        "generatedAt",
        "sources",
    }
    assert body["category"]["subdomain"]["name"] == "자사주"
    assert body["extraCategories"] is None
    assert body["quiz"][0]["answer"] is True
    assert body["generatedAt"] is None
    assert body["sources"] == []
    assert body["updatedAt"] == "2026-08-21T15:30:00+09:00"
    # DB 에 있는 개념만 이름이 붙고, 없는 개념(ghost)은 응답에서 빠진다
    assert body["related"] == [
        {"slug": "dividend", "name": "배당", "reason": "현금으로 돌려주는 다른 방식"}
    ]


async def test_detail_resolves_extra_categories(client):
    response = await client.get("/api/concepts/dividend")
    assert response.json()["extraCategories"] == [
        {
            "domain": {"slug": "macro", "name": "거시경제"},
            "subdomain": {"slug": "interest-rate", "name": "금리"},
        }
    ]
    assert response.json()["quiz"] is None


async def test_unknown_slug_returns_404_error_shape(client):
    response = await client.get("/api/concepts/없는개념")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "CONCEPT_NOT_FOUND", "message": "개념을 찾을 수 없습니다"}
    }
