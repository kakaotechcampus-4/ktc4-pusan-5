"""④ 판정 응답 읽기와 저장 전 보정 (CLASSIFICATION_DB_DRAFT 4-8). LLM 출력 하나가 CHECK 에 걸려
회차 전체가 롤백되면 안 된다. 고친 건수는 프롬프트를 고칠 신호라 남는다."""

import json
from pathlib import Path

import pytest

from app.services.classification.basis import load_basis
from app.services.classification.candidates import Candidate, collect_candidates
from app.services.classification.events import Event
from app.services.classification.judge import JudgeParseError, build_judge_message, parse_judgments
from app.services.classification.link import link_mentions

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")
CANDIDATES = {1: [Candidate("005930", "company", True),
                  Candidate("066570", "relation", False, via_stock_code="005930",
                            relation_type="competitor", relation_refs=[{"via": "005930"}])]}


def respond(*items: dict) -> str:
    return json.dumps({"judgments": list(items)}, ensure_ascii=False)


def j(stock: str, label: str, event: int = 1) -> dict:
    return {"event": event, "stock": stock, "label": label, "reason": "이유"}


def test_clean_response_is_kept() -> None:
    result = parse_judgments(respond(j("005930", "DIRECT"), j("066570", "INDIRECT_CONTEXT")), CANDIDATES)
    assert result.judgments[(1, "005930")].label == "DIRECT"
    assert not any(result.fixes.values())


def test_direct_on_capped_candidate_is_lowered() -> None:
    result = parse_judgments(respond(j("005930", "DIRECT"), j("066570", "DIRECT")), CANDIDATES)
    fixed = result.judgments[(1, "066570")]
    assert fixed.label == "INDIRECT_CONTEXT" and fixed.reason.startswith("[보정:")
    assert result.fixes["direct_lowered"] == 1


def test_missing_candidate_becomes_unknown() -> None:
    result = parse_judgments(respond(j("005930", "DIRECT")), CANDIDATES)
    assert result.judgments[(1, "066570")].label == "UNKNOWN"
    assert result.judgments[(1, "066570")].reason == "[보정: 판정 누락]"
    assert result.fixes["missing_filled"] == 1


def test_outside_stock_and_unjudged_event_are_dropped() -> None:
    """후보 밖 종목은 낼 수 없다(전제 P4)."""
    result = parse_judgments(respond(j("005930", "DIRECT"), j("066570", "UNKNOWN"),
                                     j("000660", "DIRECT"), j("005930", "DIRECT", event=9)),
                             CANDIDATES)
    assert (1, "000660") not in result.judgments
    assert result.fixes["outside_dropped"] == 2


def test_invalid_label_and_duplicate() -> None:
    result = parse_judgments(respond(j("005930", "INDIRECT"), j("005930", "DIRECT"),
                                     j("066570", "NOT_APPLICABLE")), CANDIDATES)
    assert result.judgments[(1, "005930")].label == "UNKNOWN"
    assert result.fixes["invalid_label"] == 1 and result.fixes["duplicate_dropped"] == 1


@pytest.mark.parametrize("text", ["판정 못 함", "{\"result\": []}",
                                  respond({"event": "첫째", "stock": "005930", "label": "DIRECT"})])
def test_unreadable_response_fails_the_run(text: str) -> None:
    with pytest.raises(JudgeParseError):
        parse_judgments(text, CANDIDATES)


def test_message_carries_paths_business_and_relation_notes() -> None:
    """세부 산업·관계 정보가 없으면 LLM 이 회사 사업을 짐작한다. 판정 입력의 근거다."""
    e = Event(order_index=1, scope="industry", role="cause", tense="past", sentence_indices=(1,),
              context_indices=(), mentions=("엔비디아", "HBM"), reason=None)
    links = link_mentions(e.mentions, BASIS).links
    found = collect_candidates(e, links, BASIS)
    message = build_judge_message("제목", ["엔비디아가 HBM 주문을 늘렸다."], [(e, links, found)], BASIS)
    assert "[1] 엔비디아가 HBM 주문을 늘렸다." in message
    assert "HBM → 산업 메모리반도체" in message
    assert "402340 SK스퀘어 [최대 INDIRECT_CONTEXT]" in message
    assert "메모리반도체(상장사 지분 SK하이닉스)" in message
    assert "엔비디아의 공급사 — 메모리반도체 — 범위 HBM. 단계 공급 확인" in message
