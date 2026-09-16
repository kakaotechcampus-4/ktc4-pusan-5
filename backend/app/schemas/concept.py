"""개념 페이지 스키마.

- 시드 파일(seeds/concepts/*.json) 파싱용 모델과 API 응답 모델을 함께 둔다.
- 시드 파일도 응답과 같은 camelCase 키를 쓰므로 alias_generator 를 공유한다.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from app.core.taxonomy import Taxonomy
from app.models import Concept
from app.schemas.base import CamelModel

OPTIONAL_SECTIONS = (
    "related",
    "quiz",
)


class TaxonomyNodeOut(CamelModel):
    slug: str
    name: str


class CategoryOut(CamelModel):
    domain: TaxonomyNodeOut
    subdomain: TaxonomyNodeOut


class QuizItem(CamelModel):
    question: str
    answer: bool
    explanation: str


class RelatedRef(CamelModel):
    """시드 파일에 적히는 형태. 이름은 응답을 만들 때 조인한다."""

    slug: str
    reason: str


class RelatedConcept(CamelModel):
    slug: str
    name: str
    reason: str


class ConceptSeed(CamelModel):
    """seeds/concepts/<slug>.json 한 개."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    category: str
    extra_categories: list[str] | None = None
    summary: str
    body: str
    related: list[RelatedRef] | None = None
    quiz: list[QuizItem] | None = None
    sources: list[str] = Field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        """DB 컬럼에 그대로 넣을 수 있는 dict. 컬럼명은 snake_case, JSONB 안은 단어 키만 쓴다."""
        return self.model_dump()


class ConceptListItem(CamelModel):
    slug: str
    name: str
    aliases: list[str]
    summary: str
    category: CategoryOut


class ConceptListResponse(CamelModel):
    items: list[ConceptListItem]


class ConceptDetail(CamelModel):
    slug: str
    name: str
    aliases: list[str]
    category: CategoryOut
    extra_categories: list[CategoryOut] | None
    summary: str
    body: str
    related: list[RelatedConcept] | None
    quiz: list[QuizItem] | None
    updated_at: datetime
    generated_at: datetime | None
    sources: list[str]


def _category(taxonomy: Taxonomy, category: str) -> CategoryOut:
    resolved = taxonomy.resolve(category)
    return CategoryOut(
        domain=TaxonomyNodeOut(slug=resolved.domain.slug, name=resolved.domain.name),
        subdomain=TaxonomyNodeOut(slug=resolved.subdomain.slug, name=resolved.subdomain.name),
    )


def _section(model: type[CamelModel], rows: list[dict[str, Any]] | None) -> list[Any] | None:
    if not rows:
        return None
    return [model.model_validate(row) for row in rows]


def to_list_item(concept: Concept, taxonomy: Taxonomy) -> ConceptListItem:
    return ConceptListItem(
        slug=concept.slug,
        name=concept.name,
        aliases=concept.aliases or [],
        summary=concept.summary,
        category=_category(taxonomy, concept.category),
    )


def to_detail(
    concept: Concept,
    taxonomy: Taxonomy,
    related_names: Mapping[str, str],
) -> ConceptDetail:
    """related 의 이름은 DB 조회 결과로 채우고, 없는 개념은 응답에서 뺀다."""
    related = [
        RelatedConcept(slug=item["slug"], name=related_names[item["slug"]], reason=item["reason"])
        for item in (concept.related or [])
        if item["slug"] in related_names
    ]
    extra = concept.extra_categories
    return ConceptDetail(
        slug=concept.slug,
        name=concept.name,
        aliases=concept.aliases or [],
        category=_category(taxonomy, concept.category),
        extra_categories=[_category(taxonomy, c) for c in extra] if extra else None,
        summary=concept.summary,
        body=concept.body,
        related=related or None,
        quiz=_section(QuizItem, concept.quiz),
        updated_at=concept.updated_at,
        generated_at=concept.generated_at,
        sources=concept.sources or [],
    )
