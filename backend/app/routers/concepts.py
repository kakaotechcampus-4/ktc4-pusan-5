from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AppError
from app.core.taxonomy import get_taxonomy
from app.repositories.concept import ConceptRepository
from app.schemas.concept import ConceptDetail, ConceptListResponse, to_detail, to_list_item

router = APIRouter(prefix="/api/concepts", tags=["concepts"])


async def get_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConceptRepository:
    return ConceptRepository(session)


RepositoryDep = Annotated[ConceptRepository, Depends(get_repository)]


@router.get("", response_model=ConceptListResponse)
async def list_concepts(repository: RepositoryDep) -> ConceptListResponse:
    taxonomy = get_taxonomy()
    concepts = await repository.list_all()
    return ConceptListResponse(items=[to_list_item(concept, taxonomy) for concept in concepts])


@router.get("/{slug}", response_model=ConceptDetail)
async def get_concept(slug: str, repository: RepositoryDep) -> ConceptDetail:
    concept = await repository.get_by_slug(slug)
    if concept is None:
        raise AppError("CONCEPT_NOT_FOUND", "개념을 찾을 수 없습니다", status.HTTP_404_NOT_FOUND)
    related_slugs = [item["slug"] for item in concept.related or []]
    related_names = await repository.get_names_by_slugs(related_slugs)
    return to_detail(concept, get_taxonomy(), related_names)
