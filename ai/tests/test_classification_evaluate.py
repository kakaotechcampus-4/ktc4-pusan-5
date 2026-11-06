"""정답 대조와 토큰 집계. 판정이 틀리면 프롬프트를 잘못된 방향으로 고치게 된다."""

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock

from app.services.classification import __main__ as cli
from app.services.classification import llm
from app.services.classification.basis import load_basis
from app.services.classification.evaluate import (
    Label,
    Tokens,
    load_labels,
    sentence_recall,
    stock_linked,
    tokens_of,
)
from app.services.classification.events import Event
from app.services.classification.judge import Judgment
from app.services.classification.pipeline import ClassifiedEvent

MOCK_BASIS = Path(__file__).parent / "fixtures" / "mock_classification_basis.json"
SAMSUNG, HYNIX = "005930", "000660"


def event(sentences, context=(), role="cause", mentions=("삼성전자",)) -> Event:
    return Event(order_index=1, scope="company", role=role, tense="past",
                 sentence_indices=tuple(sentences), context_indices=tuple(context),
                 mentions=tuple(mentions), reason=None)


def label(gold=(), stock="삼성전자") -> Label:
    return Label(article_id="x", kind="단일종목", stock=stock, gold=frozenset(gold), memo="")


def test_load_labels_reads_bom_and_no_cause(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_text("﻿id,유형,종목,제목,문장수,이유(한 줄),정답 문장,메모\n"
                    "a,단일종목,심텍,t,27,r,\"1,3\",\n"
                    "b,원인없음,삼성전자,t,16,r,-,함정\n", encoding="utf-8")
    labels = load_labels(path)
    assert labels["a"].gold == {1, 3}
    assert labels["b"].gold == frozenset() and labels["b"].memo == "함정"


def test_all_some_none() -> None:
    assert sentence_recall([event([1, 3])], label({1, 3})) == "all"
    assert sentence_recall([event([1])], label({1, 3})) == "some"
    assert sentence_recall([event([5])], label({1, 3})) == "none"


def test_context_sentences_count_as_covered() -> None:
    """정답에 '주어가 있는 앞 문장' 이 들어간 경우가 있다(107c21 메모). 문맥으로 내도 맞다."""
    assert sentence_recall([event([2], context=[1])], label({1, 2})) == "all"


def test_price_move_does_not_count() -> None:
    assert sentence_recall([event([1, 3], role="price_move")], label({1, 3})) == "none"


def test_no_cause_article() -> None:
    """원인 없는 기사에 다른 회사 사건이 있는 건 괜찮다. 그 종목 근거만 없으면 된다."""
    assert sentence_recall([], label()) == "pass"
    assert sentence_recall([event([1], mentions=["SK하이닉스"])], label()) == "pass"
    assert sentence_recall([event([1], mentions=["삼성전자"])], label()) == "fail"
    assert sentence_recall([event([1], role="price_move")], label()) == "pass"


def judged(sentences, *judgments: tuple[str, str], role="cause", mentions=("삼성전자",)):
    """판정까지 마친 사건. judgments 는 (종목 코드, 판정) 목록."""
    return ClassifiedEvent(
        event=event(sentences, role=role, mentions=mentions),
        judgments=[Judgment(1, code, value, None) for code, value in judgments])


def test_stock_linked_needs_the_label_stock_judgment() -> None:
    """문장을 찾았어도 정답 종목에 붙지 않았으면 맞은 게 아니다. 문장 재현율과 여기서 갈린다."""
    basis = load_basis(MOCK_BASIS)
    wrong_stock = [judged([1, 3], (HYNIX, "DIRECT"), (SAMSUNG, "NOT_APPLICABLE"))]
    assert sentence_recall([i.event for i in wrong_stock], label({1, 3})) == "all"
    assert stock_linked(wrong_stock, label({1, 3}), basis) == "none"

    assert stock_linked([judged([1, 3], (SAMSUNG, "DIRECT"))], label({1, 3}), basis) == "all"
    # 배경으로 붙은 것도 그 종목에 이어진 것이다
    assert stock_linked([judged([1, 3], (SAMSUNG, "INDIRECT_CONTEXT"))], label({1, 3}),
                        basis) == "all"
    assert stock_linked([judged([1], (SAMSUNG, "DIRECT")), judged([3], (SAMSUNG, "UNKNOWN"))],
                        label({1, 3}), basis) == "some"
    assert stock_linked([judged([1, 3], (SAMSUNG, "DIRECT"), role="price_move")],
                        label({1, 3}), basis) == "none"


def test_stock_linked_no_cause_article() -> None:
    """원인 없는 기사는 그 종목을 DIRECT 로 판정했을 때만 실패다. 배경으로 붙은 건 괜찮다."""
    basis = load_basis(MOCK_BASIS)
    assert stock_linked([], label(), basis) == "pass"
    assert stock_linked([judged([1], (SAMSUNG, "INDIRECT_CONTEXT"))], label(), basis) == "pass"
    assert stock_linked([judged([1], (HYNIX, "DIRECT"))], label(), basis) == "pass"
    assert stock_linked([judged([1], (SAMSUNG, "DIRECT"))], label(), basis) == "fail"
    # 표기가 종목 이름과 같아도 판정이 붙지 않았으면 통과다. 문장 재현율과 반대로 갈린다
    not_applied = [judged([1], (SAMSUNG, "NOT_APPLICABLE"))]
    assert sentence_recall([i.event for i in not_applied], label()) == "fail"
    assert stock_linked(not_applied, label(), basis) == "pass"


def test_stock_linked_matches_alias_and_skips_stock_outside_basis() -> None:
    basis = load_basis(MOCK_BASIS)
    assert stock_linked([judged([1], (SAMSUNG, "DIRECT"))], label({1}, stock="삼전"), basis) == "all"
    assert stock_linked([judged([1], (SAMSUNG, "DIRECT"))], label({1}, stock="KSS해운"),
                        basis) is None


def test_tokens_include_reasoning() -> None:
    usage = {"prompt_tokens": 1200, "completion_tokens": 500,
             "completion_tokens_details": {"reasoning_tokens": 300}}
    assert tokens_of(usage) == Tokens(prompt=1200, completion=500, reasoning=300)
    assert tokens_of({}).total == 0


async def test_eval_writes_result_file_with_judgments(tmp_path: Path, monkeypatch, capsys) -> None:
    articles = {"a": {"title": "삼성전자 실적", "body": "삼성전자 실적이 늘었다. 주가가 올랐다."}}
    (tmp_path / "articles.json").write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "labels.csv").write_text(
        "id,유형,종목,제목,문장수,이유(한 줄),정답 문장,메모\na,단일종목,삼성전자,t,2,r,1,\n",
        encoding="utf-8")
    response = json.dumps({"events": [
        {"scope": "company", "role": "cause", "tense": "past", "sentences": [1],
         "mentions": ["삼성전자"]},
        {"scope": "company", "role": "price_move", "tense": "past", "sentences": [2],
         "mentions": []},
    ]}, ensure_ascii=False)
    judged = json.dumps({"judgments": [
        {"event": 1, "stock": "005930", "label": "DIRECT", "reason": "회사 실적"}]})
    usage = {"prompt_tokens": 1000, "completion_tokens": 200, "cost": 0.001, "finish_reason": "stop"}

    async def complete(system, user, **kwargs):
        return (judged if "# 판정할 사건" in user else response), usage

    monkeypatch.setattr(llm, "complete", AsyncMock(side_effect=complete))
    monkeypatch.setattr(cli, "endpoint", lambda: ("http://test", "key"))

    out = tmp_path / "out.json"
    await cli.run_eval(argparse.Namespace(
        articles=tmp_path / "articles.json", ids=None, limit=None, out=out, basis=MOCK_BASIS,
        extract_model=None, link_model=None, judge_model=None))

    printed = capsys.readouterr().out
    assert "문장 all · 연결 all" in printed and "DIRECT 삼성전자" in printed
    assert "문장 재현율" in printed and "종목 연결" in printed
    saved = json.loads(out.read_text(encoding="utf-8"))
    run = saved["results"][0]["run"]
    assert saved["results"][0]["verdict"] == "all"
    assert saved["results"][0]["verdict_linked"] == "all"
    assert run["raw_response"] == response
    assert run["events"][0]["judgments"][0]["label"] == "DIRECT"
    assert set(saved["models"]) == {"extract", "judge"}


def test_review_sheet_shows_sentences_and_failed_raw_events(tmp_path: Path) -> None:
    """사람이 원문을 다시 열지 않고 판정할 수 있어야 한다. 실패한 응답의 사건도 보여 준다."""
    import csv

    from app.services.classification.evaluate import write_review

    articles = {"a": {"title": "t", "body": "삼성전자 실적이 늘었다. 주가가 올랐다."},
                "b": {"title": "t", "body": "D램 가격이 올랐다."}}
    raw = json.dumps({"events": [{"scope": "analyst_view", "role": "cause", "tense": "past",
                                  "sentences": [1], "mentions": ["D램"]}]}, ensure_ascii=False)
    result = {"results": [
        {"id": "a", "title": "t", "verdict": "all", "verdict_linked": "none",
         "label": {"kind": "단일종목", "stock": "삼성전자", "gold": [1]},
         "run": {"status": "ok", "splitter_version": "v1", "events": [
             {"order_index": 1, "scope": "company", "role": "cause", "tense": "past",
              "sentence_indices": [1], "context_indices": [], "mentions": ["삼성전자"],
              "judgments": [{"event_order": 1, "stock_code": "000660", "label": "DIRECT",
                             "reason": None}]}]}},
        {"id": "b", "title": "t", "verdict": None, "label": None,
         "run": {"status": "failed", "error": "scope 오류", "splitter_version": "v1",
                 "events": [], "raw_response": raw}},
    ]}
    labels = {"a": Label(article_id="a", kind="단일종목", stock="삼성전자", gold=frozenset({1}),
                         memo="", reason="실적 증가")}
    out = tmp_path / "review.csv"
    assert write_review(result, articles, out, labels) == 2

    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert rows[0]["정답 문장"] == "1. 삼성전자 실적이 늘었다."
    assert rows[0]["정답 이유"] == "실적 증가"
    assert "1. 삼성전자 실적이 늘었다." in rows[0]["뽑힌 사건"]
    assert rows[0]["사람: 추출 판정 (all/some/none/pass/fail)"] == ""
    assert rows[0]["자동 채점: 문장 재현율"] == "all"
    assert rows[0]["자동 채점: 종목 연결"] == "none"
    # 종목 연결이 왜 none 인지 사람이 보도록 판정을 함께 보여 준다
    assert "→ 000660 DIRECT" in rows[0]["뽑힌 사건"]
    assert rows[1]["자동 채점: 종목 연결"] == ""  # 예전 결과 파일처럼 값이 없어도 비워 둔다
    assert rows[1]["상태"].startswith("failed — scope 오류")
    assert "analyst_view" in rows[1]["뽑힌 사건"]


def test_similar_company_name_is_not_target() -> None:
    """이름이 겹치는 다른 회사는 그 종목 근거가 아니다. 연결(link)도 표기 전체로 맞춘다."""
    assert sentence_recall([event([1], mentions=["삼성전자서비스"])], label()) == "pass"


def test_review_handles_invalid_indices_and_formula_title(tmp_path: Path) -> None:
    """실패한 응답의 번호 칸에는 무엇이든 올 수 있다. 밖에서 온 제목은 엑셀 수식이 되지 않게 쓴다."""
    import csv

    from app.services.classification.evaluate import write_review

    raw = json.dumps({"events": [{"sentences": ["1", True, None, 1], "context": 3}]})
    result = {"results": [{"id": "a", "title": '=HYPERLINK("https://example.com")',
                           "run": {"status": "failed", "raw_response": raw}}]}
    out = tmp_path / "review.csv"
    assert write_review(result, {"a": {"body": "실적 증가."}}, out) == 1
    with out.open(encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    assert row["제목"].startswith("'=HYPERLINK")
    assert "1. 실적 증가." in row["뽑힌 사건"]
