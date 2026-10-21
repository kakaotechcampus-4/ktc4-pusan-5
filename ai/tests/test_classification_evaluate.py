"""정답 대조와 토큰 집계. 판정이 틀리면 프롬프트를 잘못된 방향으로 고치게 된다."""

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock

from app.services.classification import __main__ as cli
from app.services.classification import extract as extract_service
from app.services.classification.evaluate import Label, Tokens, load_labels, score, tokens_of
from app.services.classification.events import Event


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
    assert score([event([1, 3])], label({1, 3})) == "all"
    assert score([event([1])], label({1, 3})) == "some"
    assert score([event([5])], label({1, 3})) == "none"


def test_context_sentences_count_as_covered() -> None:
    """정답에 '주어가 있는 앞 문장' 이 들어간 경우가 있다(107c21 메모). 문맥으로 내도 맞다."""
    assert score([event([2], context=[1])], label({1, 2})) == "all"


def test_price_move_does_not_count() -> None:
    assert score([event([1, 3], role="price_move")], label({1, 3})) == "none"


def test_no_cause_article() -> None:
    """원인 없는 기사에 다른 회사 사건이 있는 건 괜찮다. 그 종목 근거만 없으면 된다."""
    assert score([], label()) == "pass"
    assert score([event([1], mentions=["SK하이닉스"])], label()) == "pass"
    assert score([event([1], mentions=["삼성전자"])], label()) == "fail"
    assert score([event([1], role="price_move")], label()) == "pass"


def test_tokens_include_reasoning() -> None:
    usage = {"prompt_tokens": 1200, "completion_tokens": 500,
             "completion_tokens_details": {"reasoning_tokens": 300}}
    assert tokens_of(usage) == Tokens(prompt=1200, completion=500, reasoning=300)
    assert tokens_of({}).total == 0


async def test_batch_writes_result_file_with_tokens(tmp_path: Path, monkeypatch, capsys) -> None:
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
    usage = {"prompt_tokens": 1000, "completion_tokens": 200, "cost": 0.001, "finish_reason": "stop"}
    monkeypatch.setattr(extract_service, "complete", AsyncMock(return_value=(response, usage)))

    out = tmp_path / "out.json"
    await cli.run_batch(argparse.Namespace(
        articles=tmp_path / "articles.json", ids=None, limit=None, out=out, model=None))

    printed = capsys.readouterr().out
    assert "정답 all" in printed and "1,200 토큰" in printed
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["total_tokens"] == {"prompt": 1000, "completion": 200, "reasoning": 0}
    assert saved["results"][0]["verdict"] == "all"
    assert saved["results"][0]["run"]["raw_response"] == response


def test_review_sheet_shows_sentences_and_failed_raw_events(tmp_path: Path) -> None:
    """사람이 원문을 다시 열지 않고 판정할 수 있어야 한다. 실패한 응답의 사건도 보여 준다."""
    import csv

    from app.services.classification.evaluate import write_review

    articles = {"a": {"title": "t", "body": "삼성전자 실적이 늘었다. 주가가 올랐다."},
                "b": {"title": "t", "body": "D램 가격이 올랐다."}}
    raw = json.dumps({"events": [{"scope": "analyst_view", "role": "cause", "tense": "past",
                                  "sentences": [1], "mentions": ["D램"]}]}, ensure_ascii=False)
    result = {"results": [
        {"id": "a", "title": "t", "verdict": "all",
         "label": {"kind": "단일종목", "stock": "삼성전자", "gold": [1]},
         "run": {"status": "ok", "splitter_version": "v1", "events": [
             {"order_index": 1, "scope": "company", "role": "cause", "tense": "past",
              "sentence_indices": [1], "context_indices": [], "mentions": ["삼성전자"]}]}},
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
    assert rows[1]["상태"].startswith("failed — scope 오류")
    assert "analyst_view" in rows[1]["뽑힌 사건"]
