"""발췌 방식 비교 실험의 채점 규칙. 채점이 틀리면 방식 선택이 통째로 틀린다."""

import pytest

from app.services.news_link.compare.methods import (
    MAX_SELECT,
    method_a,
    parse_selection,
    selected_text,
)
from app.services.news_link.compare.score import compare, parse_answer, parse_mark, render_report
from app.services.news_link.sentence import split_sentences


def test_answer_accepts_lists_and_ranges() -> None:
    assert parse_answer("6,7,8") == {6, 7, 8}
    assert parse_answer("6-8") == {6, 7, 8}
    assert parse_answer(" 6, 8 ") == {6, 8}
    assert parse_answer("2, 5~6") == {2, 5, 6}


def test_blank_answer_is_not_the_same_as_no_cause() -> None:
    """빈칸을 '원인 없음' 으로 읽으면 안 적은 칸이 채점된다."""
    assert parse_answer("") is None
    assert parse_answer("-") == set()
    assert parse_answer("없음") == set()


def test_unreadable_answer_stops_instead_of_guessing() -> None:
    with pytest.raises(ValueError):
        parse_answer("6번이랑 7번")


def test_marks_accept_common_spellings() -> None:
    assert parse_mark("Y") is True and parse_mark("o") is True and parse_mark("예") is True
    assert parse_mark("n") is False and parse_mark("X") is False
    assert parse_mark("") is None and parse_mark("(자동)") is None


def test_method_a_matches_the_production_excerpt() -> None:
    """A 는 운영 발췌와 같아야 한다. 번호로 되돌린 문장이 곧 fetch.py 가 싣는 글이다."""
    body = "첫째다. 둘째다. 셋째다. 넷째다."
    indices = method_a(body)
    assert indices == [1, 2, 3]
    assert selected_text(split_sentences(body), indices) == "첫째다. 둘째다. 셋째다."


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


def test_compare_counts_full_and_partial_hits() -> None:
    result = compare({6, 7, 8}, [6, 7, 8, 11])
    assert result["all_in"] and result["any_in"]
    assert result["recall"] == 1.0
    assert result["precision"] == 0.75

    miss = compare({6, 7, 8}, [1, 2, 3])
    assert not miss["all_in"] and not miss["any_in"]
    assert miss["recall"] == 0.0


def test_no_cause_article_is_scored_by_leaving_it_empty() -> None:
    assert compare(set(), []) == {"none_case": True, "none_correct": True}
    assert compare(set(), [1, 2, 3])["none_correct"] is False


def test_report_shows_where_methods_split() -> None:
    rows = [
        {"id": "aaa111", "kind": "시황", "stock": "가나전자", "answer": {6, 7, 8},
         "a": [1, 2, 3], "b": [6, 7, 8], "b_fallback": False,
         "a_chars": 120, "b_chars": 130, "c_chars": 140, "c_unsupported": ["4,210억"],
         "b_cost": 0.001, "c_cost": 0.002,
         "review": {("C", "reason"): True, ("C", "invented"): True, ("B", "sense"): True}},
    ]
    report = render_report(rows, [])
    assert "| 정답 문장 **전부** 포함 | 0/1 (0%) | 1/1 (100%) |" in report
    assert "B 만 맞힘: aaa111(가나전자)" in report
    assert "4,210억" in report
