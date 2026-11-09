"""분류 기준 JSON. 틀린 기준으로 분류하면 결과 전체를 다시 만들어야 해서 읽을 때 막는다."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.services.classification.basis import (
    BasisError,
    latest_basis_file,
    load_basis,
    parse_basis,
)
from app.services.classification.link import alias_index

MOCK_BASIS = Path(__file__).parent / "fixtures" / "mock_classification_basis.json"


def mock_data() -> dict:
    return json.loads(MOCK_BASIS.read_text(encoding="utf-8"))


def problems_of(data: dict) -> list[str]:
    with pytest.raises(BasisError) as exc:
        parse_basis(data, version="test")
    return exc.value.problems


def link(data: dict, stock: str, industry: str) -> dict:
    return next(i for i in data["stock_industries"] if i["stock"] == stock and i["industry"] == industry)


def test_shipped_basis_file_passes_every_check() -> None:
    """운영 기준 파일이 깨져 있으면 분류를 시작조차 못 한다."""
    basis = load_basis(latest_basis_file())
    assert len(basis.stocks) == 33
    assert {"005935", "042700", "298040", "138040", "011200", "033780"} <= basis.stocks.keys()
    assert all(len(basis.links_of(code)) > 0 for code in basis.stocks)


def test_version_is_file_sha256() -> None:
    basis = load_basis(MOCK_BASIS)
    assert basis.version == hashlib.sha256(MOCK_BASIS.read_bytes()).hexdigest()


def test_ancestors_go_up_to_the_krx_group() -> None:
    assert load_basis(MOCK_BASIS).ancestors("memory") == ["memory", "semiconductor", "krx_electronics"]


def test_stake_link_caps_direct() -> None:
    basis = load_basis(MOCK_BASIS)
    stake = next(x for x in basis.links_of("402340") if x.industry_code == "memory")
    assert not stake.direct_allowed
    assert all(x.direct_allowed for x in basis.links_of("000660"))


def test_planned_link_caps_direct() -> None:
    data = mock_data()
    link(data, "066570", "home_appliance")["stage"] = "planned"
    basis = parse_basis(data, version="test")
    assert not basis.links_of("066570")[0].direct_allowed


def test_competitor_is_stored_once_in_fixed_order() -> None:
    """방향 없는 관계는 종목끼리는 코드가 작은 쪽, 외부 기업과는 종목 쪽이 from 이다."""
    basis = load_basis(MOCK_BASIS)
    competitors = {(r.from_code, r.to_code) for r in basis.relations if r.relation_type == "competitor"}
    assert ("005930", "066570") in competitors  # 파일에는 066570 → 005930 으로 적었다
    assert ("005930", "apple") in competitors
    assert ("068270", "samsung_epis") in competitors


def test_stake_link_needs_matching_ownership() -> None:
    """산업 기사와 회사 기사가 같은 지분을 다르게 보지 않게 한다(INDUSTRY_REVIEW 2-5)."""
    data = mock_data()
    data["company_relations"] = [r for r in data["company_relations"]
                                 if not (r["from"] == "402340" and r["type"] == "ownership")]
    assert any("짝이 되는 ownership" in p for p in problems_of(data))


def test_subsidiary_link_needs_subsidiary_alias() -> None:
    """자회사 이름이 나온 기사가 모회사에 닿으려면 별칭에 있어야 한다."""
    data = mock_data()
    link(data, "005930", "display")["via_company"] = "삼성SDC"
    assert any("subsidiaries 에 없다" in p for p in problems_of(data))


def test_stock_links_to_the_smallest_industry_only() -> None:
    data = mock_data()
    link(data, "000660", "memory")["industry"] = "semiconductor"
    assert any("가장 작은 분류" in p for p in problems_of(data))


def test_own_link_has_no_via_company() -> None:
    data = mock_data()
    link(data, "000660", "memory")["via_company"] = "SK하이닉스"
    assert any("via_company" in p for p in problems_of(data))


def test_relation_needs_one_listed_stock() -> None:
    data = mock_data()
    data["company_relations"].append(
        {"from": "nvidia", "to": "apple", "type": "supplier", "industry": None, "source": "mock"})
    assert any("적어도 한쪽은" in p for p in problems_of(data))


def test_relation_key_is_unique_per_industry() -> None:
    """10-29: (from, to, 종류, 산업) 하나에 한 행. 제품 범위가 여럿이면 note 에 함께 적는다."""
    data = mock_data()
    data["company_relations"].append(copy.deepcopy(data["company_relations"][2]))
    assert any("중복" in p for p in problems_of(data))


def test_external_company_cannot_be_a_listed_stock() -> None:
    data = mock_data()
    data["external_companies"][0]["stock_code"] = "005930"
    assert any("분류 대상 종목이다" in p for p in problems_of(data))


def test_external_company_without_relation_is_rejected() -> None:
    data = mock_data()
    data["external_companies"].append({"code": "tsmc", "name": "TSMC", "aliases": []})
    assert any("관계가 없다" in p for p in problems_of(data))


def test_one_alias_points_to_one_target() -> None:
    data = mock_data()
    data["stocks"][1]["aliases"].append("삼전")
    assert any("함께 가리킨다" in p for p in problems_of(data))


def test_blocked_alias_cannot_be_used_but_blocked_official_name_is_skipped() -> None:
    """"SK" 는 SK㈜ 의 공식 이름이지만 그룹을 가리키는 일이 많아 표기로 잇지 않는다."""
    data = mock_data()
    data["stocks"][0]["aliases"].append("삼성")
    assert any("막은 표기" in p for p in problems_of(data))
    index = alias_index(load_basis(MOCK_BASIS))
    assert "sk" not in index and index["sk㈜"].stock_code == "034730"


def test_parent_cycle_is_rejected() -> None:
    data = mock_data()
    data["industries"][0]["parent"] = "memory"
    assert any("고리" in p for p in problems_of(data))


def test_all_problems_are_reported_at_once() -> None:
    data = mock_data()
    data["stocks"].append({"code": "12345", "name": "짧은코드"})
    data["industries"].append({"code": "Bad", "name": "대문자", "parent": None})
    assert len(problems_of(data)) >= 2
