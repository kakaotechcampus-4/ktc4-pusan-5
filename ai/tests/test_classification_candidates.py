"""③ 후보 모으기 (CLASSIFICATION_DB_DRAFT 5-1). 기준표는 후보만 만들고, 붙일지는 ④ 가 정한다."""

from pathlib import Path

from app.services.classification.basis import load_basis
from app.services.classification.candidates import collect_candidates
from app.services.classification.events import Event
from app.services.classification.link import alias_index, link_mentions

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")


def event(scope: str, *mentions: str, role: str = "cause") -> Event:
    return Event(order_index=1, scope=scope, role=role, tense="past", sentence_indices=(1,),
                 context_indices=(), mentions=mentions, reason=None)


def candidates(scope: str, *mentions: str, role: str = "cause") -> dict:
    links = link_mentions(mentions, BASIS, alias_index(BASIS)).links
    return {c.stock_code: c for c in collect_candidates(event(scope, *mentions, role=role), links, BASIS)}


def test_draft_example_fcbga_low_mid_reaches_only_its_own_companies() -> None:
    """같은 기판이라도 형제 세부 산업(고사양·일반 PCB)으로는 넓히지 않는다(전제 P11)."""
    found = candidates("industry", "중·저사양 FC-BGA")
    assert set(found) == {"900002"}
    assert found["900002"].path == "industry" and found["900002"].direct_allowed


def test_draft_example_company_event_and_its_competitor() -> None:
    found = candidates("company", "B사", "D사")
    assert {k: c.path for k, c in found.items()} == {
        "900002": "company", "900004": "company", "900001": "relation"}
    a = found["900001"]
    assert not a.direct_allowed and a.via_stock_code == "900002" and a.relation_type == "competitor"
    # D사는 직접 언급으로 대표 경로가 company 지만, B사와의 공급 관계는 버리지 않는다
    assert found["900004"].relation_refs[0]["candidate_is"] == "customer"


def test_parent_industry_reaches_all_child_companies_and_stake_is_capped() -> None:
    found = candidates("industry", "반도체 업황")
    assert set(found) == {"005930", "000660", "402340"}
    assert not found["402340"].direct_allowed
    assert found["402340"].link.exposure == "stake"


def test_company_event_does_not_spread_through_its_industry_words() -> None:
    """"삼성전자, D램 가격 상승에 실적 개선" 이 다른 메모리 회사로 퍼지면 안 된다."""
    found = candidates("company", "삼성전자", "D램")
    assert found["005930"].path == "company"
    assert "000660" not in found and "402340" not in found
    assert found["066570"].path == "relation"  # 가전 경쟁 관계가 있어서일 뿐. 판정이 거른다


def test_macro_and_market_make_no_candidates() -> None:
    assert candidates("macro", "삼성전자") == {}
    assert candidates("market", "삼성전자") == {}


def test_price_move_does_not_go_through_relations() -> None:
    found = candidates("company", "SK하이닉스", role="price_move")
    assert set(found) == {"000660"}


def test_external_company_is_origin_not_candidate() -> None:
    found = candidates("company", "엔비디아")
    assert set(found) == {"000660", "005930"}
    assert all(c.path == "relation" and c.via_external_code == "nvidia" for c in found.values())
    assert found["000660"].relation_refs[0]["candidate_is"] == "supplier"


def test_relations_survive_when_industry_path_wins() -> None:
    """"엔비디아, HBM 주문 확대" 를 산업 사건으로 봐도 엔비디아 공급 관계는 판정에 넘어간다."""
    found = candidates("industry", "엔비디아", "HBM")
    assert found["000660"].path == "industry"
    assert found["000660"].relation_refs == [{
        "via": "nvidia", "type": "supplier", "candidate_is": "supplier", "industry": "memory",
        "note": "범위 HBM. 단계 공급 확인"}]


def test_one_stock_with_several_relations_is_one_candidate() -> None:
    """애플 소식 → 삼성전자는 OLED 공급사이자 스마트폰 경쟁사. 후보는 하나, 관계는 둘 다."""
    found = candidates("company", "애플")
    refs = found["005930"].relation_refs
    assert {r["candidate_is"] for r in refs} == {"supplier", "competitor"}


def test_subsidiary_mention_follows_only_that_subsidiarys_business() -> None:
    """하만 기사 → 삼성전자. 엔비디아 HBM 공급·가전 경쟁으로 넓히지 않는다."""
    harman = candidates("company", "하만")
    assert harman["005930"].via_subsidiaries == ("하만",)
    assert set(harman) == {"005930"}
    display = candidates("company", "삼성디스플레이")
    assert set(display) == {"005930"}  # 애플 OLED 공급은 애플(외부 기업)이 후보가 아니라 무관
    assert display["005930"].relation_refs == []


def test_subsidiary_restriction_does_not_apply_to_ownership() -> None:
    """지분 관계는 사업 범위가 아니라 보유자를 찾는 것이다."""
    data_found = candidates("company", "SK스퀘어")
    assert data_found["034730"].relation_type == "ownership"
    assert data_found["034730"].relation_refs[0]["candidate_is"] == "owner"


def test_external_subsidiary_reaches_competitor() -> None:
    """삼성바이오에피스(외부 기업의 자회사 표기) → 셀트리온 경쟁."""
    found = candidates("company", "삼성바이오에피스")
    assert set(found) == {"068270"} and found["068270"].via_external_code == "samsung_epis"


def test_order_is_company_then_industry_then_relation() -> None:
    found = list(candidates("industry", "B사", "PCB").values())
    assert [(c.stock_code, c.path) for c in found] == [
        ("900002", "company"), ("900003", "industry"), ("900004", "relation"), ("900001", "relation")]
