"""LLM 사건 응답 검사. 없는 문장 번호·지어낸 표기가 저장되지 않게 한다."""

import json

import pytest

from app.services.classification.events import EventParseError, parse_events

SENTENCES = ["D램 가격이 급등했다.", "LG전자 주가는 3% 내렸다."]


def response(*events: dict) -> str:
    return json.dumps({"events": list(events)}, ensure_ascii=False)


def event(**overrides) -> dict:
    base = {"scope": "industry", "role": "cause", "tense": "past",
            "sentences": [1], "context": [], "mentions": ["D램"]}
    return {**base, **overrides}


def test_code_fence_is_stripped() -> None:
    parsed = parse_events("```json\n" + response(event()) + "\n```", SENTENCES)
    assert parsed.events[0].mentions == ("D램",)


def test_indices_are_sorted_and_deduplicated() -> None:
    parsed = parse_events(response(event(sentences=[2, 1, 2], context=[1])), SENTENCES)
    assert parsed.events[0].sentence_indices == (1, 2)
    assert parsed.events[0].context_indices == ()  # 근거 문장과 겹치는 문맥 번호는 뺀다


@pytest.mark.parametrize("bad", [[3], [0], [True], ["1"]])
def test_index_out_of_range_fails_the_run(bad: list) -> None:
    with pytest.raises(EventParseError):
        parse_events(response(event(sentences=bad)), SENTENCES)


def test_event_without_evidence_fails_the_run() -> None:
    with pytest.raises(EventParseError):
        parse_events(response(event(sentences=[])), SENTENCES)


def test_unknown_scope_fails_the_run() -> None:
    with pytest.raises(EventParseError):
        parse_events(response(event(scope="sector")), SENTENCES)


def test_tense_value_in_role_fails_the_run() -> None:
    """모델이 role 칸에 tense 값을 넣은 적이 있다(2026-10-21). 형식 오류로 막는다."""
    with pytest.raises(EventParseError):
        parse_events(response(event(role="future", tense="future")), SENTENCES)


def test_broken_json_fails_the_run() -> None:
    with pytest.raises(EventParseError):
        parse_events('{"events": [', SENTENCES)


def test_mention_not_in_article_is_dropped_and_reported() -> None:
    parsed = parse_events(response(event(mentions=["D램", "삼성전자"])), SENTENCES)
    assert parsed.events[0].mentions == ("D램",)
    assert parsed.dropped_mentions == [(1, "삼성전자")]


def test_mention_may_come_from_another_sentence() -> None:
    """근거 문장이 '이 회사' 처럼 대명사여도 표기는 기사 안에 있으면 된다."""
    parsed = parse_events(response(event(sentences=[1], mentions=["LG전자"])), SENTENCES)
    assert parsed.events[0].mentions == ("LG전자",)


def test_events_over_prompt_limit_are_kept() -> None:
    """프롬프트의 '많아도 8개' 는 권고다. 넘었다고 회차를 버리지 않는다.
    9번째 사건이 정답 문장을 담은 기사가 있었다(2026-10-21 실행, 756ccd)."""
    parsed = parse_events(response(*[event()] * 9), SENTENCES)
    assert len(parsed.events) == 9
