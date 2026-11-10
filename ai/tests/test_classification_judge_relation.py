"""④ 판정에서 관계 경로 후보만 Jev 로 판정하기 (CLASSIFICATION_RELATION_JUDGE=jev).

호출은 모두 가짜로 바꾼다. 확인하는 것
- '○○가 이 회사의 주주' 관계뿐인 후보는 묻지 않고 해당 없음(코드 규칙)
- 관계마다 예/아니오 하나, 문턱 YES 이상이면 간접
- jev 일 때 LLM 판정 호출에는 관계 후보가 들어가지 않고, 관계 후보만 있으면 LLM 을 부르지 않는다
- 기본값 luna 는 지금처럼 호출 하나가 모든 후보를 판정한다
"""

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.llm import jev
from app.llm.client import LLMError
from app.services.classification import judge as judge_module
from app.services.classification import judge_relation, llm, pipeline
from app.services.classification.basis import load_basis
from app.services.classification.candidates import Candidate
from app.services.classification.events import Event
from app.services.classification.judge import Judging, judge
from app.services.classification.judge_relation import YES, decide, relation_questions

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")
EVENT = Event(order_index=1, scope="company", role="cause", tense="past", sentence_indices=(2,),
              context_indices=(1,), mentions=("삼성전자",), reason="이유")
SENTENCES = ["삼성전자가 3분기 실적을 냈다.", "메모리 출하가 늘었다.", "다른 문장."]
COMPANY = Candidate("005930", "company", True)
COMPETITOR = Candidate("000660", "relation", False, via_stock_code="005930", relation_type="competitor",
                       relation_refs=[{"via": "005930", "candidate_is": "competitor", "note": "범위 D램"}])
OWNED_ONLY = Candidate("402340", "relation", False, via_stock_code="005930", relation_type="ownership",
                       relation_refs=[{"via": "005930", "candidate_is": "owned"}])
OWNER = Candidate("034730", "relation", False, via_stock_code="005930", relation_type="ownership",
                  relation_refs=[{"via": "005930", "candidate_is": "owner"},
                                 {"via": "005930", "candidate_is": "supplier", "note": "범위 부품"}])


def test_owned_only_is_not_asked_and_not_passed() -> None:
    questions, plan = relation_questions(EVENT, OWNED_ONLY, BASIS)
    assert questions == {} and plan.owned == 1
    label, reason = decide(plan, {})
    assert label == "NOT_APPLICABLE" and "코드" in reason


def test_one_question_per_relation_with_scope() -> None:
    questions, plan = relation_questions(EVENT, OWNER, BASIS)
    assert len(questions) == 2 and [role for _, role, _ in plan.questions] == ["owner", "supplier"]
    texts = [q["instructions"] for q in questions.values()]
    assert "삼성전자의 주주다" in texts[0] and "사건 1" in texts[0]
    assert "삼성전자의 공급사다(관계 범위: 부품)" in texts[1]
    assert all(q["type"] == "noul" for q in questions.values())


def test_competitor_question_puts_scope_first_and_lists_unrelated_news() -> None:
    """경쟁사 질문은 관계 범위 제품을 따로 적고, 경쟁과 무관한 일(주가·주식 매매·인사·사내 시스템)을 뺀다."""
    questions, _ = relation_questions(EVENT, COMPETITOR, BASIS)
    (question,) = questions.values()
    text = question["instructions"]
    assert "경쟁하는 제품은 'D램' 이다. 사건 1이(가) 바로 이 제품 시장에서 삼성전자의" in text
    assert all(word in text for word in ("주가 등락", "주식 매매", "인사", "사내 업무 시스템", "지난 일 소개"))
    assert question["criteria"]["true"] == "'D램' 제품 시장에서 삼성전자의 경쟁 조건이 바뀌는 일이다"
    assert "제품 경쟁과 무관한 일" in question["criteria"]["false"]


def test_scope_takes_only_product_range_from_note() -> None:
    """메모의 근거 수준·단계·검토 메모는 질문에 넣지 않고 '범위' 제품만 넣는다(#115 리뷰)."""
    note = ("범위 배터리 셀(전기차·ESS·로봇 등 용도, 셀을 담은 모듈·팩·ESS 제품 포함). "
            "실제 당사자 SK온. 근거 reported. MVP 채택 판단 전")
    ref = {"via": "005930", "candidate_is": "competitor", "industry": "memory", "note": note}
    candidate = Candidate("000660", "relation", False, via_stock_code="005930", relation_type="competitor",
                          relation_refs=[ref])
    (question,) = relation_questions(EVENT, candidate, BASIS)[0].values()
    text = question["instructions"]
    assert ("경쟁하는 제품은 '배터리 셀(전기차·ESS·로봇 등 용도, 셀을 담은 모듈·팩·ESS 제품 포함)' 이다. "
            "실제 사업 회사는 SK온이다. 사건 1이(가)") in text
    assert all(word not in text + str(question["criteria"]) for word in ("근거", "reported", "MVP", "범위 배터리"))


@pytest.mark.parametrize(("ref", "scope"), [
    ({"industry": "memory", "note": "23a 범위 HBM, 단계 공급 확인, 근거 official(HBM3 공급. 이후 세대는 따로 확인). "
                                    "23b 범위 차세대 메모리 기술협력, 단계 협의·개발, 근거 official"},
     "HBM, 차세대 메모리 기술협력"),
    ({"industry": "memory", "note": "근거 reported"}, "메모리반도체"),
    ({"industry": None, "note": None}, "범위 메모 없음"),
])
def test_scope_text_cases(ref: dict, scope: str) -> None:
    assert judge_relation.scope_text(BASIS, ref) == scope
    assert judge_relation.party_text(ref) == ""


def test_other_relations_keep_plain_criteria() -> None:
    questions, _ = relation_questions(EVENT, OWNER, BASIS)
    assert all(q["criteria"] == {"true": "그렇다", "false": "아니다"} for q in questions.values())


@pytest.mark.parametrize(("value", "label"), [(YES, "INDIRECT_CONTEXT"), (0.9, "INDIRECT_CONTEXT"),
                                              (YES - 0.01, "NOT_APPLICABLE")])
def test_threshold(value: float, label: str) -> None:
    questions, plan = relation_questions(EVENT, COMPETITOR, BASIS)
    (key,) = questions
    assert decide(plan, {key: {"noul": value}})[0] == label


def test_any_relation_yes_is_enough() -> None:
    questions, plan = relation_questions(EVENT, OWNER, BASIS)
    first, second = questions
    label, reason = decide(plan, {first: {"noul": 0.02}, second: {"noul": 0.4}})
    assert label == "INDIRECT_CONTEXT" and "공급사" in reason


def test_missing_answer_is_none() -> None:
    _, plan = relation_questions(EVENT, COMPETITOR, BASIS)
    assert decide(plan, {})[0] is None


def test_state_has_full_text_and_event_sentences() -> None:
    state = judge_relation.build_state("제목", SENTENCES, [EVENT])
    assert state["본문"] == " ".join(SENTENCES)
    assert state["사건 1"] == "삼성전자가 3분기 실적을 냈다. 메모리 출하가 늘었다."


@pytest.fixture
def jev_mode(monkeypatch):
    monkeypatch.setattr(settings, "classification_relation_judge", "jev")
    monkeypatch.setattr(settings, "jev_url", "https://example.invalid/v1/decisions")
    monkeypatch.setattr(settings, "jev_api_key", "test-key")
    monkeypatch.setattr(settings, "jev_input_krw_per_m", 59.0)


def fake_calls(monkeypatch, *, noul: float = 0.5, jev_error: str | None = None):
    sent = {"llm": [], "jev": []}

    async def fake_llm_call(step, prompt_name, user, *, model=None):
        sent["llm"].append(user)
        reply = {"judgments": [{"event": 1, "stock": "005930", "label": "DIRECT", "reason": "실적"}]}
        return llm.StepCall(step=step, model="luna", prompt_sha256="x",
                            raw_response=json.dumps(reply), usage={"cost": 0.001})

    async def fake_decide(state, questions, *, model=None):
        sent["jev"].append((state, questions))
        if jev_error:
            raise LLMError(jev_error)
        return {q: {"type": "noul", "noul": noul} for q in questions}, {"prompt_tokens": 1000}

    monkeypatch.setattr(llm, "call", fake_llm_call)
    monkeypatch.setattr(jev, "decide", fake_decide)
    return sent


async def test_jev_mode_splits_candidates(monkeypatch, jev_mode) -> None:
    sent = fake_calls(monkeypatch, noul=0.3)
    result = await judge("제목", SENTENCES, [(EVENT, [], [COMPANY, COMPETITOR, OWNED_ONLY])], BASIS)
    assert result.error is None
    (message,) = sent["llm"]
    assert "005930 삼성전자" in message and "000660" not in message and "402340" not in message
    ((_, questions),) = sent["jev"]
    assert len(questions) == 1  # 경쟁 관계 하나만 묻는다. 주주 관계뿐인 후보는 묻지 않는다
    labels = {stock: j.label for (_, stock), j in result.judgments.items()}
    assert labels == {"005930": "DIRECT", "000660": "INDIRECT_CONTEXT", "402340": "NOT_APPLICABLE"}
    record = result.relation_call.usage_record()
    assert record["cost"] == pytest.approx(1000 * 59 / 1_000_000) and record["model"] == settings.jev_model


async def test_only_relation_candidates_skip_llm(monkeypatch, jev_mode) -> None:
    sent = fake_calls(monkeypatch)
    result = await judge("제목", SENTENCES, [(EVENT, [], [COMPETITOR])], BASIS)
    assert sent["llm"] == [] and result.call is None and result.relation_call is not None
    assert result.judgments[(1, "000660")].label == "INDIRECT_CONTEXT"


async def test_owned_only_needs_no_call_at_all(monkeypatch, jev_mode) -> None:
    sent = fake_calls(monkeypatch)
    result = await judge("제목", SENTENCES, [(EVENT, [], [OWNED_ONLY])], BASIS)
    assert sent == {"llm": [], "jev": []} and result.relation_call is None
    assert result.judgments[(1, "402340")].label == "NOT_APPLICABLE"


async def test_jev_failure_fails_the_judging(monkeypatch, jev_mode) -> None:
    fake_calls(monkeypatch, jev_error="Jev 호출 실패: HTTP 500")
    result = await judge("제목", SENTENCES, [(EVENT, [], [COMPANY, COMPETITOR])], BASIS)
    assert result.error and "judge_relation" in result.error


async def test_jev_mode_without_settings_stops(monkeypatch, jev_mode) -> None:
    fake_calls(monkeypatch)
    monkeypatch.setattr(settings, "jev_url", None)
    with pytest.raises(RuntimeError, match="JEV_URL"):
        await judge("제목", SENTENCES, [(EVENT, [], [COMPANY, COMPETITOR])], BASIS)


async def test_luna_mode_sends_everything_to_llm(monkeypatch) -> None:
    monkeypatch.setattr(settings, "classification_relation_judge", "luna")
    sent = fake_calls(monkeypatch)
    result = await judge("제목", SENTENCES, [(EVENT, [], [COMPANY, COMPETITOR])], BASIS)
    assert sent["jev"] == [] and result.relation_call is None
    assert "000660" in sent["llm"][0]


async def test_pipeline_keeps_relation_usage(monkeypatch, jev_mode) -> None:
    async def fake_judge(title, sentences, items, basis, *, model=None):
        relation_call = judge_relation.JevCall(step="judge_relation", model="typesafe/jev-1.14",
                                               prompt_sha256="x", usage={"prompt_tokens": 10})
        return Judging(call=None, relation_call=relation_call)

    async def fake_extract(title, sentences, *, model=None):
        from app.services.classification.extract import Extraction
        call = llm.StepCall(step="extract", model="luna", prompt_sha256="x", raw_response="{}",
                            usage={"cost": 0.001})
        return Extraction(call=call, events=[EVENT])

    monkeypatch.setattr(pipeline, "judge", fake_judge)
    monkeypatch.setattr(pipeline, "extract_events", fake_extract)
    result = await pipeline.classify("제목", " ".join(SENTENCES), BASIS)
    assert result.status == "ok" and "judge_relation" in result.usage
    assert result.usage["judge_relation"]["cost_basis"] == "jev_input_tokens"


def test_judge_module_reads_the_setting() -> None:
    # 기본값은 지금 동작 그대로다
    assert type(settings).model_fields["classification_relation_judge"].default == "luna"
    assert judge_module.settings is settings


def test_require_is_noop_for_luna(monkeypatch) -> None:
    monkeypatch.setattr(settings, "classification_relation_judge", "luna")
    monkeypatch.setattr(settings, "jev_url", None)
    judge_relation.require()


def test_require_needs_elice_and_jev_settings(monkeypatch, jev_mode) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    with pytest.raises(RuntimeError, match="elice"):
        judge_relation.require()
    monkeypatch.setattr(settings, "llm_provider", "elice")
    judge_relation.require()
    monkeypatch.setattr(settings, "jev_url", None)
    with pytest.raises(RuntimeError, match="JEV_URL"):
        judge_relation.require()
