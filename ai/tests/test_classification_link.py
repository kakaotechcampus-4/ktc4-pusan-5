"""② 표기 연결. 별칭 사전이 먼저고, LLM 코드 선택은 목록 안의 코드만 받는다(전제 P4)."""

import json
from pathlib import Path

import pytest

from app.services.classification.basis import load_basis
from app.services.classification.link import (
    Unresolved,
    code_list,
    link_mentions,
    parse_link_response,
)

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")


def test_alias_name_subsidiary_and_external() -> None:
    result = link_mentions(["Samsung Electronics", "삼성디스플레이", "NVIDIA", "D램"], BASIS)
    by_mention = {link.mention: link for link in result.links}
    assert by_mention["Samsung Electronics"].stock_code == "005930"
    assert by_mention["삼성디스플레이"].stock_code == "005930"
    assert by_mention["삼성디스플레이"].via_subsidiary == "삼성디스플레이"
    assert by_mention["NVIDIA"].external_code == "nvidia"
    assert by_mention["D램"].industry_code == "memory"
    assert all(link.linked_by == "alias" for link in result.links)


def test_blocked_and_unknown_mentions_are_kept_apart() -> None:
    """"삼성" 은 LLM 에도 보내지 않는다. 사전에 없는 표기만 LLM 이 고른다."""
    result = link_mentions(["삼성", "메모리 업체들"], BASIS)
    assert result.links == [] and result.blocked == ["삼성"] and result.unresolved == ["메모리 업체들"]


def test_code_list_leaves_out_krx_groups() -> None:
    listed = code_list(BASIS)
    assert "memory 메모리반도체 (상위: 반도체)" in listed
    assert "krx_electronics" not in listed


def test_llm_choice_is_limited_to_listed_codes_and_asked_mentions() -> None:
    asked = [Unresolved(1, "메모리 업체들"), Unresolved(2, "현대차그룹"), Unresolved(2, "TV 회사")]
    text = json.dumps({"links": [
        {"event": 1, "mention": "메모리 업체들", "code": "memory"},
        {"event": 2, "mention": "현대차그룹", "code": None},
        {"event": 2, "mention": "TV 회사", "code": "krx_electronics"},  # 맨 위 산업은 목록 밖
        {"event": 3, "mention": "묻지 않은 표기", "code": "005930"},
    ]}, ensure_ascii=False)
    links = parse_link_response(text, asked, BASIS)
    assert list(links) == [1]
    assert links[1][0].industry_code == "memory" and links[1][0].linked_by == "llm_code"


@pytest.mark.parametrize("row", [
    None,
    "문자열",
    {"event": [], "mention": "메모리 업체들", "code": "memory"},  # 배열은 집합에서 찾을 수 없다
    {"event": True, "mention": "메모리 업체들", "code": "memory"},
    {"event": 1, "mention": {}, "code": "memory"},
    {"mention": "메모리 업체들", "code": "memory"},
    {"event": 1, "mention": "메모리 업체들", "code": ["memory"]},
    {"event": 1, "mention": "메모리 업체들", "code": {}},
    {"event": 1, "mention": "메모리 업체들", "code": 3},
    {"event": 1, "mention": "메모리 업체들"},  # null 과 다르다. 답을 안 준 것이다
])
def test_malformed_row_is_a_format_error(row) -> None:
    """ValueError 라야 회차가 failed 로 남는다. 조용히 버리면 표기가 연결되지 않은 채 ok 가 된다."""
    text = json.dumps({"links": [row]}, ensure_ascii=False)
    with pytest.raises(ValueError, match="links 의 행|알아볼 수 없다|code 는"):
        parse_link_response(text, [Unresolved(1, "메모리 업체들")], BASIS)


def test_null_code_means_no_match_and_is_not_an_error() -> None:
    text = json.dumps({"links": [{"event": 1, "mention": "현대차그룹", "code": None}]},
                      ensure_ascii=False)
    assert parse_link_response(text, [Unresolved(1, "현대차그룹")], BASIS) == {}
