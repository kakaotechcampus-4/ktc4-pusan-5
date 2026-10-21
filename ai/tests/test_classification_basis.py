"""분류 기준 JSON. 틀린 기준으로 분류하면 결과 전체를 다시 만들어야 해서 읽을 때 막는다."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.services.classification.basis import BasisError, load_basis, parse_basis

MOCK_BASIS = Path(__file__).parent / "fixtures" / "mock_classification_basis.json"


def mock_data() -> dict:
    return json.loads(MOCK_BASIS.read_text(encoding="utf-8"))


def problems_of(data: dict) -> list[str]:
    with pytest.raises(BasisError) as exc:
        parse_basis(data, version="test")
    return exc.value.problems


def test_version_is_file_sha256() -> None:
    basis = load_basis(MOCK_BASIS)
    assert basis.version == hashlib.sha256(MOCK_BASIS.read_bytes()).hexdigest()


def test_ancestors_follow_news_parent_not_krx_group() -> None:
    basis = load_basis(MOCK_BASIS)
    assert basis.ancestors("memory") == ["memory", "semiconductor"]
    assert "krx_electronics" not in basis.reachable_industries("005930")


def test_reachable_industries_exclude_siblings() -> None:
    """SK하이닉스(메모리)에 형제 산업 파운드리는 닿지 않는다."""
    basis = load_basis(MOCK_BASIS)
    assert basis.reachable_industries("000660") == {"memory", "semiconductor"}


def test_only_confirmed_links_are_used() -> None:
    """SK스퀘어–지주회사는 미검토라 없는 연결로 본다."""
    basis = load_basis(MOCK_BASIS)
    assert basis.industries_of("402340") == ["memory"]


def test_confirmed_link_needs_evidence_and_reviewer() -> None:
    data = mock_data()
    data["links"][0]["evidence"] = ""
    assert any("evidence" in p for p in problems_of(data))


def test_krx_group_cannot_be_news_parent() -> None:
    data = mock_data()
    data["industries"][0]["parent"] = "krx_electronics"
    assert any("상위 krx_electronics" in p for p in problems_of(data))


def test_stock_cannot_link_to_krx_group() -> None:
    data = mock_data()
    data["links"][0]["industry_code"] = "krx_electronics"
    assert any("KRX 그룹에는 연결하지 않는다" in p for p in problems_of(data))


def test_one_alias_points_to_one_target() -> None:
    data = mock_data()
    data["industries"][1]["aliases"].append("하이닉스")
    assert any("하이닉스" in p and "함께 가리킨다" in p for p in problems_of(data))


def test_blocked_alias_cannot_be_used() -> None:
    """'삼성' 은 여러 회사를 가리킨다. 별칭으로 넣으면 문맥 없이 삼성전자로 확정된다."""
    data = mock_data()
    data["stocks"][0]["aliases"].append("삼성")
    assert any("막은 표기" in p for p in problems_of(data))


def test_parent_cycle_is_rejected() -> None:
    data = mock_data()
    data["industries"][0]["parent"] = "memory"  # semiconductor → memory → semiconductor
    assert any("고리" in p for p in problems_of(data))


def test_all_problems_are_reported_at_once() -> None:
    data = copy.deepcopy(mock_data())
    data["links"][0]["status"] = "maybe"
    data["stocks"][0]["code"] = "5930"
    assert len(problems_of(data)) >= 2
