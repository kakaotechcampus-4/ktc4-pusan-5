"""분류 체계(seeds/taxonomy.json) 로더.

개념의 category 문자열("대분류slug/중분류slug")을 한글 이름까지 붙은 형태로 풀어준다.
JSON 파일이 원본이고 DB에는 넣지 않는다.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"
TAXONOMY_PATH = SEEDS_DIR / "taxonomy.json"


class UnknownCategoryError(ValueError):
    """taxonomy 에 없는 분류를 조회했을 때"""


@dataclass(frozen=True)
class TaxonomyNode:
    slug: str
    name: str


@dataclass(frozen=True)
class ResolvedCategory:
    domain: TaxonomyNode
    subdomain: TaxonomyNode


class Taxonomy:
    def __init__(self, domains: list[dict]) -> None:
        self._domains = domains
        self._index: dict[str, ResolvedCategory] = {}
        for domain in domains:
            parent = TaxonomyNode(slug=domain["slug"], name=domain["name"])
            for child in domain["children"]:
                key = f"{parent.slug}/{child['slug']}"
                self._index[key] = ResolvedCategory(
                    domain=parent,
                    subdomain=TaxonomyNode(slug=child["slug"], name=child["name"]),
                )

    @property
    def domains(self) -> list[dict]:
        return self._domains

    def has(self, category: str) -> bool:
        return category in self._index

    def resolve(self, category: str) -> ResolvedCategory:
        try:
            return self._index[category]
        except KeyError:
            raise UnknownCategoryError(f"알 수 없는 분류입니다: {category}") from None


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    with path.open(encoding="utf-8") as f:
        return Taxonomy(json.load(f))


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    """기동 후 첫 조회 때 한 번만 읽고 재사용한다."""
    return load_taxonomy()
