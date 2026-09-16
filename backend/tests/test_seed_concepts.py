import copy

from app.core.taxonomy import get_taxonomy, load_taxonomy
from app.seeds.concepts import CONCEPTS_DIR, collect_seeds, load_raw_seeds, validate_seeds

TAXONOMY = load_taxonomy()

VALID = {
    "slug": "treasury-stock",
    "name": "자사주",
    "aliases": ["자기주식"],
    "category": "shareholder-return/treasury-stock",
    "extraCategories": None,
    "summary": "한 줄 요약",
    "body": "앞 문단입니다.\n\n[배당](dividend) 을 함께 봅니다.",
    "related": [{"slug": "dividend", "reason": "현금으로 돌려주는 다른 방식"}],
    "quiz": [{"question": "질문", "answer": True, "explanation": "해설"}],
    "sources": [],
}

OTHER = {
    "slug": "dividend",
    "name": "배당",
    "aliases": [],
    "category": "shareholder-return/dividend",
    "extraCategories": None,
    "summary": "요약",
    "body": "본문",
    "related": None,
    "quiz": None,
    "sources": [],
}


def _raw(**overrides):
    data = copy.deepcopy(VALID)
    data.update(overrides)
    return {"treasury-stock.json": data, "dividend.json": copy.deepcopy(OTHER)}


def test_valid_seeds_pass():
    seeds, errors = validate_seeds(_raw(), TAXONOMY)
    assert errors == []
    assert [seed.slug for seed in seeds] == ["treasury-stock", "dividend"]
    assert seeds[1].quiz is None
    assert seeds[0].related[0].slug == "dividend"


def test_broken_body_link_is_rejected():
    seeds, errors = validate_seeds(_raw(body="[없는 개념](ghost) 참조"), TAXONOMY)
    assert seeds == []
    assert any("ghost" in error and "treasury-stock.json" in error for error in errors)


def test_broken_related_slug_is_rejected():
    seeds, errors = validate_seeds(
        _raw(related=[{"slug": "ghost", "reason": "없는 개념"}]), TAXONOMY
    )
    assert seeds == []
    assert any("related" in error and "ghost" in error for error in errors)


def test_unknown_category_is_rejected():
    seeds, errors = validate_seeds(_raw(category="shareholder-return/없는중분류"), TAXONOMY)
    assert seeds == []
    assert any("taxonomy" in error for error in errors)

    _, extra_errors = validate_seeds(_raw(extraCategories=["macro/없는중분류"]), TAXONOMY)
    assert any("extraCategories" in error for error in extra_errors)


def test_empty_optional_section_is_rejected():
    seeds, errors = validate_seeds(_raw(quiz=[]), TAXONOMY)
    assert seeds == []
    assert any("quiz" in error for error in errors)


def test_filename_must_match_slug():
    raw = {"wrong-name.json": copy.deepcopy(VALID)}
    seeds, errors = validate_seeds(raw, TAXONOMY)
    assert seeds == []
    assert any("파일명" in error for error in errors)


def test_unknown_field_is_rejected():
    seeds, errors = validate_seeds(_raw(typo="오타"), TAXONOMY)
    assert seeds == []
    assert errors


def test_real_seed_files_pass_validation():
    seeds, errors = collect_seeds(CONCEPTS_DIR, get_taxonomy())
    assert errors == []
    assert len(seeds) == 11
    assert {seed.slug for seed in seeds} == {
        "treasury-stock",
        "shareholder-return",
        "interest-rate",
        "circular-financing",
        "per",
        "capex",
        "disclosure",
        "dividend",
        "financial-statements",
        "roe",
        "depreciation",
    }


def test_real_seed_rows_match_db_columns():
    seeds, _ = collect_seeds(CONCEPTS_DIR, get_taxonomy())
    row = next(seed for seed in seeds if seed.slug == "treasury-stock").to_row()
    assert set(row) == {
        "slug",
        "name",
        "aliases",
        "category",
        "extra_categories",
        "summary",
        "body",
        "related",
        "quiz",
        "sources",
    }
    assert row["related"][0]["slug"] == "shareholder-return"
    assert row["quiz"][0]["answer"] is True


def test_load_raw_seeds_reports_broken_json(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    raw, errors = load_raw_seeds(tmp_path)
    assert raw == {}
    assert any("broken.json" in error for error in errors)
