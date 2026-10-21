"""종목별 조립. DRAFT 5절 예시 기사와 12절 PostgreSQL 실행 결과표를 옮겼다.

DRAFT 와 하나 다르다. 등락만 말하는 ③(price_move)은 근거 후보에서 뺀다(assemble.py).
"""

import json
from pathlib import Path

from app.services.classification.assemble import ClassifiedEvent, assemble
from app.services.classification.basis import load_basis, parse_basis
from app.services.classification.events import parse_events
from app.services.classification.link import link_mentions

MOCK_BASIS = Path(__file__).parent / "fixtures" / "mock_classification_basis.json"

ARTICLE = [
    "D램 가격이 급등했다.",
    "메모리 품귀로 TV 제조사 원가 부담이 커졌다.",
    "LG전자 주가는 3% 내렸다.",
    "미국 금리 인하 기대에 코스피는 1% 올랐다.",
    "반도체 업황 회복 기대가 커졌다.",
]
# LLM 이 냈다고 치는 응답. 사건 ①~⑤ 는 문장 ①~⑤ 와 같다
MOCK_LLM_RESPONSE = json.dumps({"events": [
    {"scope": "industry", "role": "cause", "tense": "past", "sentences": [1], "mentions": ["D램"]},
    {"scope": "industry", "role": "cause", "tense": "past", "sentences": [2],
     "mentions": ["TV 제조사"]},
    {"scope": "company", "role": "price_move", "tense": "past", "sentences": [3],
     "mentions": ["LG전자"]},
    {"scope": "macro", "role": "cause", "tense": "past", "sentences": [4],
     "mentions": ["미국 금리", "코스피"]},
    {"scope": "industry", "role": "outlook", "tense": "future", "sentences": [5],
     "mentions": ["반도체 업황"]},
]}, ensure_ascii=False)


def classify(response: str, sentences: list[str], basis, source_card_id: int = 1):
    out = []
    for event in parse_events(response, sentences).events:
        links = link_mentions(event.mentions, basis).links
        out.append(ClassifiedEvent(source_card_id=source_card_id, event=event, links=tuple(links)))
    return out


def table(items, stock_code: str, basis) -> dict[str, list[int]]:
    rows: dict[str, list[int]] = {}
    for assembled in assemble(items, stock_code, basis):
        rows.setdefault(assembled.path, []).append(assembled.event.order_index)
    return rows


def test_draft_example_matches_documented_result() -> None:
    basis = load_basis(MOCK_BASIS)
    items = classify(MOCK_LLM_RESPONSE, ARTICLE, basis)
    # LG전자 — ③ "주가는 3% 내렸다" 는 등락만 말해서 빠진다
    assert table(items, "066570", basis) == {"industry": [2], "macro": [4]}
    assert table(items, "000660", basis) == {"industry": [1, 5], "macro": [4]}  # SK하이닉스
    assert table(items, "005930", basis) == {"industry": [1, 2, 5], "macro": [4]}  # 삼성전자
    assert table(items, "402340", basis) == {"industry": [1, 5], "macro": [4]}  # SK스퀘어
    assert table(items, "005380", basis) == {"macro": [4]}  # 현대차


def test_company_event_does_not_spread_through_industry() -> None:
    """회사 사건에 산업 표기가 섞여도 다른 메모리 회사로 퍼지지 않는다."""
    basis = load_basis(MOCK_BASIS)
    sentences = ["삼성전자, 메모리 가격 상승에 실적 개선."]
    response = json.dumps({"events": [
        {"scope": "company", "role": "cause", "tense": "past", "sentences": [1],
         "mentions": ["삼성전자", "메모리"]},
    ]}, ensure_ascii=False)
    items = classify(response, sentences, basis)
    assert table(items, "005930", basis) == {"company": [1]}
    assert table(items, "000660", basis) == {}


def test_price_move_is_kept_in_extraction_but_not_assembled() -> None:
    """등락만 말한 사건은 추출 결과에 남는다. LLM 이 무엇을 price_move 로 봤는지 확인할 수 있게."""
    basis = load_basis(MOCK_BASIS)
    items = classify(MOCK_LLM_RESPONSE, ARTICLE, basis)
    assert [i.event.order_index for i in items if i.event.role == "price_move"] == [3]
    assert 3 not in [a.event.order_index for a in assemble(items, "066570", basis)]


def test_price_move_with_reason_in_same_sentence_is_a_cause() -> None:
    """이유가 같은 문장에 있으면 LLM 이 cause 로 낸다. 그러면 직접 근거다."""
    basis = load_basis(MOCK_BASIS)
    sentences = ["원가 부담 우려에 LG전자 주가는 3% 내렸다."]
    response = json.dumps({"events": [
        {"scope": "company", "role": "cause", "tense": "past", "sentences": [1],
         "mentions": ["LG전자"]},
    ]}, ensure_ascii=False)
    assert table(classify(response, sentences, basis), "066570", basis) == {"company": [1]}


def test_unconfirmed_link_carries_nothing() -> None:
    """연결이 미검토로 돌아가면 산업 사건이 그 종목에 붙지 않는다."""
    data = json.loads(MOCK_BASIS.read_text(encoding="utf-8"))
    for link in data["links"]:
        if link["stock_code"] == "000660":
            link["status"] = "unreviewed"
    basis = parse_basis(data, version="test")
    items = classify(MOCK_LLM_RESPONSE, ARTICLE, basis)
    assert table(items, "000660", basis) == {"macro": [4]}


def test_ambiguous_mention_stays_unresolved() -> None:
    basis = load_basis(MOCK_BASIS)
    result = link_mentions(["삼성", "Samsung Electronics", "TSMC"], basis)
    assert [link.stock_code for link in result.links] == ["005930"]
    assert result.unresolved == ["삼성", "TSMC"]
