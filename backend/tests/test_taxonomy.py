import json

import pytest

from app.core.taxonomy import (
    TAXONOMY_PATH,
    Taxonomy,
    UnknownCategoryError,
    load_taxonomy,
)

SAMPLE = [
    {
        "slug": "valuation",
        "name": "밸류에이션",
        "children": [{"slug": "relative-value", "name": "상대가치"}],
    }
]


def test_resolve_returns_domain_and_subdomain_names():
    taxonomy = Taxonomy(SAMPLE)
    resolved = taxonomy.resolve("valuation/relative-value")
    assert resolved.domain.slug == "valuation"
    assert resolved.domain.name == "밸류에이션"
    assert resolved.subdomain.slug == "relative-value"
    assert resolved.subdomain.name == "상대가치"


def test_unknown_category_raises():
    taxonomy = Taxonomy(SAMPLE)
    assert taxonomy.has("valuation/relative-value")
    assert not taxonomy.has("valuation/없는중분류")
    with pytest.raises(UnknownCategoryError):
        taxonomy.resolve("valuation/없는중분류")
    with pytest.raises(UnknownCategoryError):
        taxonomy.resolve("valuation")  # 대분류만으로는 조회할 수 없다


def test_seed_taxonomy_file_has_12_domains_with_5_children_each():
    taxonomy = load_taxonomy()
    domains = taxonomy.domains
    assert len(domains) == 12
    assert all(len(domain["children"]) == 5 for domain in domains)
    assert taxonomy.resolve("shareholder-return/treasury-stock").subdomain.name == "자사주"


def test_seed_taxonomy_slugs_are_unique_and_kebab_case():
    raw = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    domain_slugs = [domain["slug"] for domain in raw]
    assert len(domain_slugs) == len(set(domain_slugs))
    for domain in raw:
        child_slugs = [child["slug"] for child in domain["children"]]
        assert len(child_slugs) == len(set(child_slugs))
        for slug in [domain["slug"], *child_slugs]:
            assert slug.replace("-", "").isalnum() and slug.islower()
