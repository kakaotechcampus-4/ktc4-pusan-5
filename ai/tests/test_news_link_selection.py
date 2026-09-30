"""종목별 문장 선택. LLM 은 가짜로 바꿔 끼운다.

여기서 보는 것은 모델의 판단이 아니라 **번호를 받아 원문을 꺼내는 코드 쪽 규칙**이다.
모델이 무엇을 고르는지는 평가 데이터로 따로 잰다.
"""

from datetime import UTC, datetime

import pytest

from app.llm.client import LLMError
from app.services.news_link import selection
from app.services.news_link.schema import LinkBody
from app.services.news_link.selection import (
    MAX_SELECT,
    needs_previous,
    parse_selection,
    select_sentences,
    selected_text,
    with_context,
)


def test_selection_parses_json_even_inside_a_code_block() -> None:
    assert parse_selection('```json\n{"selected": [7, 6, 7]}\n```', 12) == [6, 7]
    assert parse_selection('{"selected": []}', 12) == []


@pytest.mark.parametrize(
    "text",
    [
        '{"selected": [0, 3]}',  # 번호는 1부터
        '{"selected": [13]}',  # 문장이 12개뿐
        '{"selected": [1, 2, 3, 4, 5]}',  # MAX_SELECT 초과
        '{"selected": ["6"]}',  # 문자열
        '{"selected": [true]}',  # bool 이 int 로 통과하면 안 된다
        "6, 7, 8",  # JSON 이 아님
        '{"picked": [6]}',  # 키가 다름
    ],
)
def test_selection_rejects_rule_violations_instead_of_fixing_them(text: str) -> None:
    """고쳐 쓰면 모델이 규칙을 얼마나 어기는지가 안 보인다."""
    assert MAX_SELECT == 4
    assert parse_selection(text, 12) is None


def test_selected_text_is_the_original_sentences() -> None:
    sentences = ["첫째다.", "둘째다.", "셋째다."]
    assert selected_text(sentences, [1, 3]) == "첫째다. 셋째다."


# ── 앞 문장 붙이기. PR #34 리뷰에서 정한 규칙 ──────────────────────────


def test_sentence_taking_over_the_previous_one_brings_it() -> None:
    sentences = [
        "삼성전자가 미국 공장 증설을 발표했다.",
        "이에 따라 장비주가 일제히 올랐다.",
        "이처럼 증설 소식이 이어지고 있다.",
    ]
    assert with_context(sentences, [2]) == [1, 2]
    # 한 칸만 붙인다. 붙인 문장(2)이 또 앞을 받아도 1 까지 거슬러 올라가지 않는다
    assert with_context(sentences, [3]) == [2, 3]
    assert with_context(sentences, [1, 2]) == [1, 2]


@pytest.mark.parametrize(
    "sentence",
    [
        "다만 시장에서는 미국 생산능력 2배 확대 소식에 투자심리가 자극된 것으로 풀이된다.",
        "하지만 현재 확인되는 것은 양산 수주가 아니라 프로토타입 단계다.",
        "그러나 실적 개선 속도는 예상보다 느렸다.",
        "반면 경쟁사는 협력을 발표했다.",
    ],
)
def test_contrast_alone_does_not_bring_the_previous_one(sentence: str) -> None:
    """역접 뒤 문장은 혼자 읽어도 뜻이 서는 경우가 많았다. 붙였더니 흐려지기도 했다(가온전선)."""
    assert not needs_previous(sentence)
    assert with_context(["별다른 공시는 없었다.", sentence], [2]) == [2]


def test_contrast_followed_by_a_back_reference_brings_it() -> None:
    """'이후' 가 앞 내용을 가리킨다. 앞 문장 없이는 무엇 이후인지 모른다."""
    sentences = ["장중 한때 3만4천750원(8.59%)까지 치솟기도 했다.", "그러나 이후 오름폭은 축소됐다."]
    assert with_context(sentences, [2]) == [1, 2]
    assert needs_previous("다만, 이에 따라 목표주가는 낮췄다.")


def test_quoted_opener_still_counts() -> None:
    assert needs_previous("\"이는 수요 회복 신호\"라는 평가가 나왔다.")
    assert not needs_previous("\"다만 과열이다\"라는 말이 나왔다.")


def test_first_sentence_has_nothing_to_attach() -> None:
    assert with_context(["이에 따라 첫 문장이다.", "둘째다."], [1]) == [1]


# ── select_sentences ─────────────────────────────────────────────


def _link(sentences: list[str], excerpt: str | None = None) -> LinkBody:
    return LinkBody(
        url="https://example.com/news/1", status="ok", title="가나전자 신제품 공개",
        excerpt=excerpt, sentences=sentences, fetched_at=datetime.now(UTC),
    )


def _reply(monkeypatch, answer: str | Exception) -> list[str]:
    """모델 대신 answer 를 돌려준다. 모델에 보낸 user 메시지를 모아 돌려준다."""
    sent: list[str] = []

    async def fake_complete(system: str, user: str, **kwargs) -> tuple[str, dict]:
        sent.append(user)
        if isinstance(answer, Exception):
            raise answer
        return answer, {"prompt_tokens": 120, "completion_tokens": 9}

    monkeypatch.setattr(selection, "complete", fake_complete)
    return sent


async def test_selected_sentences_come_from_the_body_verbatim(monkeypatch) -> None:
    sentences = ["가나전자가 신제품을 공개했다.", "이에 따라 주가가 3% 올랐다.", "날씨는 맑았다."]
    _reply(monkeypatch, '{"selected": [2]}')

    picked = await select_sentences("가나전자", _link(sentences))

    assert picked.status == "selected"
    assert picked.model_indices == [2]
    assert picked.indices == [1, 2], "'이에 따라' 가 받는 앞 문장을 코드가 붙인다"
    assert picked.excerpt == "가나전자가 신제품을 공개했다. 이에 따라 주가가 3% 올랐다."
    assert picked.usage["completion_tokens"] == 9
    assert picked.prompt_sha256 and len(picked.prompt_sha256) == 64


async def test_model_sees_numbered_sentences_with_the_stock_and_title(monkeypatch) -> None:
    sent = _reply(monkeypatch, '{"selected": [1]}')

    await select_sentences("가나전자", _link(["첫째다.", "둘째다."]))

    assert "종목: 가나전자" in sent[0]
    assert "제목: 가나전자 신제품 공개" in sent[0]
    assert "[1] 첫째다.\n[2] 둘째다." in sent[0]


async def test_empty_selection_means_the_article_is_not_about_the_stock(monkeypatch) -> None:
    _reply(monkeypatch, '{"selected": []}')

    picked = await select_sentences("한국전력", _link(["생산자물가가 올랐다."], "생산자물가가 올랐다."))

    assert picked.status == "none"
    # 앞 3문장으로 대체하지 않는다. 대체하면 '이 종목 기사가 아니다' 는 판단이 사라진다
    assert picked.excerpt is None
    assert picked.indices == []


async def test_rule_violation_falls_back_to_the_lead(monkeypatch) -> None:
    sentences = ["첫째다.", "둘째다.", "셋째다.", "넷째다.", "다섯째다."]
    _reply(monkeypatch, '{"selected": [1, 2, 3, 4, 5]}')

    picked = await select_sentences("가나전자", _link(sentences, "첫째다. 둘째다. 셋째다."))

    assert picked.status == "fallback"
    assert picked.excerpt == "첫째다. 둘째다. 셋째다."
    assert picked.indices == [1, 2, 3]
    assert picked.model_indices == []
    assert picked.raw == '{"selected": [1, 2, 3, 4, 5]}', "무엇을 어겼는지 볼 수 있게 남긴다"


async def test_call_failure_falls_back_without_raising(monkeypatch) -> None:
    """링크 하나의 호출 실패로 나머지까지 멈추면 안 된다."""
    _reply(monkeypatch, LLMError("LLM 호출 실패: HTTP 429 rate limited"))

    picked = await select_sentences("가나전자", _link(["첫째다."], "첫째다."))

    assert picked.status == "error"
    assert "429" in (picked.error or "")
    assert picked.excerpt == "첫째다."


async def test_missing_settings_are_not_hidden_as_a_fallback(monkeypatch) -> None:
    """키가 없는데 앞 3문장으로 대체하면 모든 링크가 조용히 대체된 채로 끝난다."""
    _reply(monkeypatch, RuntimeError("LLM_PROVIDER=elice 인데 설정이 없다: LLM_API_KEY"))

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        await select_sentences("가나전자", _link(["첫째다."], "첫째다."))


async def test_link_without_body_is_not_sent_to_the_model(monkeypatch) -> None:
    sent = _reply(monkeypatch, '{"selected": [1]}')
    pdf = LinkBody(url="https://file.hanaw.com/r.pdf", status="pdf", fetched_at=datetime.now(UTC))

    picked = await select_sentences("가나전자", pdf)

    assert picked.status == "no_body"
    assert sent == []


def test_whole_body_stays_out_of_serialization_and_logs() -> None:
    """본문 전량이 보고서 입력이나 로그로 새면 토큰이 몇 배가 된다."""
    link = _link(["본문 전체의 첫 문장이다.", "본문 전체의 둘째 문장이다."], excerpt="발췌")
    assert "sentences" not in link.model_dump()
    assert "본문 전체" not in link.model_dump_json()
    assert "본문 전체" not in repr(link)
