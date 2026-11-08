"""③ 홍보성 사건 Jev (promo.py). Jev·LLM 은 부르지 않는다 — 응답을 바꿔 끼워 OR 규칙과 실패 처리만 본다."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError
from app.services.classification import promo
from app.services.classification.basis import load_basis
from app.services.classification.pipeline import classify
from tests.test_classification_pipeline import fake_llm

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")
TITLE = "LG전자 소식"
LG_EVENT = {"events": [{"scope": "company", "role": "cause", "tense": "past", "sentences": [1],
                        "mentions": ["LG전자"]}]}
NO_JUDGMENTS = {"judgments": []}  # 빠진 후보는 판정이 UNKNOWN 으로 채운다
# 정규식에 없는 표현(출연). 실험에서 Jev 만 홍보성으로 본 기사(미소금융 8천억 출연)를 줄였다
JEV_ONLY = "LG전자가 미소금융재단에 8000억 원을 출연한다."
BOTH_PATHS = {"066570": "company", "005930": "relation"}


@pytest.fixture
def jev_on(monkeypatch):
    """settings 는 개발자 각자의 ai/.env 를 읽는다. 그 값에 따라 결과가 달라지지 않게 고정한다."""
    s = promo.settings
    monkeypatch.setattr(s, "classification_promo_jev", True)
    monkeypatch.setattr(s, "llm_provider", "elice")
    monkeypatch.setattr(s, "jev_url", "https://mlapi.run/jev-test/v1/decisions")
    monkeypatch.setattr(s, "jev_api_key", "jev-only")
    monkeypatch.setattr(s, "jev_model", "typesafe/jev-1.14")
    monkeypatch.setattr(s, "jev_input_krw_per_m", 59.0)


def fake_jev(monkeypatch, probability: float | None = None,
             error: Exception | None = None) -> AsyncMock:
    async def decide(state, questions, **kwargs):
        if error:
            raise error
        answers = {name: {"type": "noul", "noul": probability} for name in questions}
        return answers, {"prompt_tokens": 1000, "model": "typesafe/jev-1.14", "cost_currency": "KRW"}

    mock = AsyncMock(side_effect=decide)
    monkeypatch.setattr(promo.jev, "decide", mock)
    return mock


def paths(result) -> dict[str, str]:
    return {c.stock_code: c.path for c in result.events[0].candidates}


async def test_sure_jev_promo_drops_relation_candidates(monkeypatch, jev_on) -> None:
    """정규식이 못 잡은 홍보성 사건을 Jev 가 0.9 이상으로 보면 경쟁사 후보를 만들지 않는다."""
    fake_llm(monkeypatch, extract=LG_EVENT, judge=NO_JUDGMENTS)
    jev = fake_jev(monkeypatch, 0.95)
    result = await classify(TITLE, JEV_ONLY, BASIS)

    assert result.status == "ok", result.error
    assert paths(result) == {"066570": "company"}  # LG전자 자신은 그대로
    assert result.events[0].promo_jev == 0.95
    state, questions = jev.await_args.args
    assert state["사건 1"] == JEV_ONLY and set(questions) == {"e1"}
    record = result.usage["promo"]
    assert record["probabilities"] == {"1": 0.95} and record["threshold"] == promo.PROMO_MIN
    assert record["cost"] == pytest.approx(0.059) and record["error"] is None
    assert result.cost == pytest.approx(0.059 + 0.002)  # 추출·판정(각 0.001)과 함께 합친다


async def test_unsure_jev_keeps_relation_candidates(monkeypatch, jev_on) -> None:
    """확신이 낮은 구간에는 할인 행사·전시회 같은 사업 기사가 섞인다(실험 14-2). 거르지 않는다."""
    fake_llm(monkeypatch, extract=LG_EVENT, judge=NO_JUDGMENTS)
    fake_jev(monkeypatch, 0.6)
    result = await classify(TITLE, JEV_ONLY, BASIS)
    assert paths(result) == BOTH_PATHS
    assert result.events[0].promo_jev == 0.6


async def test_regex_hit_is_not_asked_again(monkeypatch, jev_on) -> None:
    """정규식이 이미 걸렀으면 관계 후보가 없어 Jev 를 부르지 않는다. 비용도 없다."""
    fake_llm(monkeypatch, extract=LG_EVENT, judge=NO_JUDGMENTS)
    jev = fake_jev(monkeypatch, 0.99)
    result = await classify(TITLE, "LG전자 임직원들이 연말 봉사활동에 나섰다.", BASIS)
    assert paths(result) == {"066570": "company"}
    jev.assert_not_awaited()
    assert "promo" not in result.calls and result.events[0].promo_jev is None


async def test_event_without_relation_is_not_asked(monkeypatch, jev_on) -> None:
    """등락 사건은 관계로 넘기지 않으므로 물을 것이 없다."""
    price_move = {"events": [{**LG_EVENT["events"][0], "role": "price_move"}]}
    fake_llm(monkeypatch, extract=price_move, judge=NO_JUDGMENTS)
    jev = fake_jev(monkeypatch, 0.99)
    await classify(TITLE, "LG전자 주가가 3% 올랐다.", BASIS)
    jev.assert_not_awaited()


async def test_jev_failure_keeps_run_ok_with_regex_only(monkeypatch, jev_on) -> None:
    """Jev 가 실패해도 이미 비용을 쓴 추출까지 버리지 않는다. 정규식만 본 결과로 이어 간다."""
    fake_llm(monkeypatch, extract=LG_EVENT, judge=NO_JUDGMENTS)
    fake_jev(monkeypatch, error=LLMError("Jev 호출 실패: HTTP 500"))
    result = await classify(TITLE, JEV_ONLY, BASIS)

    assert result.status == "ok" and result.error is None
    assert paths(result) == BOTH_PATHS
    record = result.usage["promo"]
    assert record["error"].startswith("promo: Jev 호출 실패")
    assert record["cost"] == 0.0 and record["cost_basis"] == "unavailable"


async def test_off_does_not_call_jev(monkeypatch) -> None:
    monkeypatch.setattr(promo.settings, "classification_promo_jev", False)
    fake_llm(monkeypatch, extract=LG_EVENT, judge=NO_JUDGMENTS)
    jev = fake_jev(monkeypatch, 0.99)
    result = await classify(TITLE, JEV_ONLY, BASIS)
    jev.assert_not_awaited()
    assert paths(result) == BOTH_PATHS and "promo" not in result.usage


def test_require_refuses_non_elice(monkeypatch, jev_on) -> None:
    """Jev 비용은 원화다. OpenRouter 의 달러 비용과 한 합계에 섞이면 안 된다."""
    promo.require()
    monkeypatch.setattr(promo.settings, "llm_provider", "openrouter")
    with pytest.raises(RuntimeError, match="elice"):
        promo.require()


def test_require_checks_jev_settings(monkeypatch, jev_on) -> None:
    monkeypatch.setattr(promo.settings, "jev_url", None)
    with pytest.raises(RuntimeError, match="JEV_URL"):
        promo.require()


def test_bad_answers_are_left_to_regex() -> None:
    """답이 없거나 0~1 이 아니면 그 사건은 확률 없이 둔다(정규식만 본다)."""
    from app.services.classification.events import Event

    events = [Event(order_index=n, scope="company", role="cause", tense="past",
                    sentence_indices=(1,), context_indices=(), mentions=("LG전자",), reason=None)
              for n in (1, 2, 3, 4)]
    answers = {"e1": {"noul": True}, "e2": {"noul": 1.5}, "e3": {"choice": "true"}, "e4": {"noul": 0.92}}
    assert promo.parse_answers(answers, events) == {4: 0.92}
    assert not promo.is_promo(None) and promo.is_promo(0.9) and not promo.is_promo(0.89)
