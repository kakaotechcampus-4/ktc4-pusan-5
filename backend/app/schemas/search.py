from typing import Literal

from app.schemas.base import CamelModel


class StockSearchItem(CamelModel):
    code: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]


class ConceptSearchItem(CamelModel):
    slug: str
    name: str
    summary: str


class SearchResponse(CamelModel):
    query: str
    stocks: list[StockSearchItem]
    concepts: list[ConceptSearchItem]
