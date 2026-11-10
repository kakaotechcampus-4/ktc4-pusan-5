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


def candidates_with_text(text: str, *mentions: str) -> dict:
    links = link_mentions(mentions, BASIS, alias_index(BASIS)).links
    found = collect_candidates(event("company", *mentions), links, BASIS, text)
    return {c.stock_code: c.path for c in found}


def test_promotional_event_does_not_reach_competitor() -> None:
    """LG전자 수상 기사가 경쟁사 삼성전자의 후보가 되던 일(PR #103). LG전자 자신은 그대로 후보다."""
    for text in [
        "LG전자, AI 워시콤보 캠페인으로 '2026 올해의 브랜드상' 수상",  # 실제 기사 제목(2026-11-01)
        "LG전자가 한국광고학회가 주관하는 올해의 브랜드상을 수상했다.",
        "LG전자 임직원들이 연말 봉사활동에 나섰다.",
        "LG전자가 이웃돕기 성금 10억 원을 기부했다.",
        # v2: 수집 뉴스에서 v1 이 놓친 표현 (실제 기사 제목을 LG전자로 바꿔 씀)
        "LG전자, 美 밴더빌트대에 첫 캠퍼스 라운지 개관",
        "LG전자, 세계조경가협회 글로벌 조경상 수상",
        "LG전자가 SK하이닉스로부터 감사패를 받았다.",
        "LG전자 임직원 봉사단이 김장 나눔 행사를 열었다.",
        "LG전자, 무형유산 담은 2027년 달력 배포",
        "LG전자, 창사 이래 첫 개인주주 초청 간담회 개최",
    ]:
        assert candidates_with_text(text, "LG전자") == {"066570": "company"}, text


def test_business_event_still_reaches_competitor() -> None:
    """생산·가격 같은 사업 사건은 경쟁사로 넘어간다. 비슷한 글자가 섞여도 홍보성으로 보지 않는다."""
    for text in [
        "LG전자 창원 공장 생산 라인이 화재로 멈췄다.",
        "LG전자가 4분기부터 TV 가격을 10% 올린다.",  # '분기부터' 안의 '기부'
        "LG전자가 수상 태양광 사업에 진출한다.",  # 물 위의 태양광. 상을 받은 게 아니다
        # v2 에서 일부러 뺀 말·예외 (사업 기사에 걸리던 것)
        "LG전자, K-세일페스타 맞아 TV 최대 30% 할인",  # 페스타·할인은 가격 소식
        "LG전자가 인천공항 라운지에 AI 가전을 공급한다.",  # 브랜드 라운지가 아니다
        "LG전자, 신제품 전시회에서 OLED TV 공개",
        "LG전자 사장이 창립기념식 대신 美 공장을 찾았다.",  # 기념식 대신 사업 일정
        "[공모주달력] LG전자 협력사 청약 일정",
    ]:
        assert candidates_with_text(text, "LG전자") == {"066570": "company", "005930": "relation"}, text
    # 문장을 넘기지 않으면 예전처럼 거르지 않는다
    assert candidates_with_text("", "LG전자") == {"066570": "company", "005930": "relation"}


def test_promo_from_outside_also_stops_relation() -> None:
    """Jev 가 홍보성으로 본 사건(promo.py)은 정규식에 안 걸려도 관계로 넘기지 않는다."""
    links = link_mentions(("LG전자",), BASIS, alias_index(BASIS)).links
    found = collect_candidates(event("company", "LG전자"), links, BASIS,
                               "LG전자가 미소금융재단에 8000억 원을 출연한다.", promo=True)
    assert {c.stock_code: c.path for c in found} == {"066570": "company"}


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
