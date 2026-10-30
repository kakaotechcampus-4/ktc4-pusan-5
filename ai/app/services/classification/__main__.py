"""사건 추출을 돌려 본다. 프롬프트를 고치면서 결과를 눈으로 보는 용도다. DB 에 쓰지 않는다.

기사 하나
    uv run python -m app.services.classification 기사.txt --title "제목"
        --basis tests/fixtures/mock_classification_basis.json

실험 기사 묶음 (eval_data/*/articles.json). 같은 폴더에 labels.csv 가 있으면 정답과 대조한다
    uv run python -m app.services.classification --articles eval_data/news_compare_tg/articles.json
    … --limit 3          앞 3건만 (프롬프트를 고친 직후 싸게 확인할 때)
    … --ids de97da,fa52b1

묶음 결과는 articles.json 옆에 classify_<시각>.json 으로 남긴다(eval_data 는 git 에 안 올라간다).

사람이 볼 검토표 (LLM 을 부르지 않는다. 결과 파일 옆에 review_<시각>.csv, 엑셀로 연다)
    uv run python -m app.services.classification --articles eval_data/news_compare_tg/articles.json
        --review eval_data/news_compare_tg/classify_<시각>.json
기사마다 토큰·비용을 찍고 마지막에 합계를 낸다. LLM 은 .env 의 설정(LLM_PROVIDER 등)대로 부른다.
"""

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.core.scope import KST
from app.llm.client import cost as cost_usd
from app.services.classification import splitter
from app.services.classification.basis import Basis, load_basis
from app.services.classification.evaluate import (
    Tokens,
    load_labels,
    score,
    tokens_line,
    tokens_of,
    write_review,
)
from app.services.classification.extract import ExtractionRun, extract_events
from app.services.classification.link import alias_index, link_mentions


def print_events(run: ExtractionRun, body: str, basis: Basis | None) -> None:
    sentences = splitter.split(body, run.splitter_version)
    if not run.events:
        print("사건 없음 — 이유가 될 내용이 없는 기사로 판단")
    index = alias_index(basis) if basis else None
    for event in run.events:
        print(f"\n[{event.order_index}] {event.scope} / {event.role} / {event.tense}"
              f"  문장 {list(event.sentence_indices)}  문맥 {list(event.context_indices)}")
        for i in (*event.context_indices, *event.sentence_indices):
            mark = "  (문맥)" if i in event.context_indices else ""
            print(f"    {i}. {sentences[i - 1]}{mark}")
        print(f"    표기 {list(event.mentions)}")
        if basis:
            result = link_mentions(event.mentions, basis, index)
            linked = [f"{link.mention}→{link.stock_code or link.industry_code}" for link in result.links]
            print(f"    연결 {linked}  미연결 {result.unresolved}")
        if event.reason:
            print(f"    이유 {event.reason}")
    if run.dropped_mentions:
        print(f"\n원문에 없어 뺀 표기 {run.dropped_mentions}")


async def run_one(args: argparse.Namespace) -> None:
    body = args.file.read_text(encoding="utf-8")
    basis = load_basis(args.basis) if args.basis else None
    run = await extract_events(body, args.title, model=args.model)
    print(f"상태 {run.status}  모델 {run.model}  문장 {run.sentence_count}")
    print(f"토큰 {tokens_line(tokens_of(run.usage))}  비용 ${cost_usd(run.usage):.5f}")
    if run.error:
        print(f"오류 {run.error}")
    if run.status != "ok":
        if run.raw_response:
            print("--- 응답 원문 ---\n" + run.raw_response)
        return
    print_events(run, body, basis)


async def run_batch(args: argparse.Namespace) -> None:
    articles: dict = json.loads(args.articles.read_text(encoding="utf-8"))
    labels_path = args.articles.parent / "labels.csv"
    labels = load_labels(labels_path) if labels_path.is_file() else {}
    if args.ids:
        # 같은 id 를 두 번 적으면 LLM 도 두 번 부른다. 순서는 지키고 한 번만 남긴다
        ids = list(dict.fromkeys(part.strip() for part in args.ids.split(",") if part.strip()))
    else:
        ids = list(articles)
    # 오타 난 id 가 섞이면 앞 기사들에 비용을 쓴 뒤에야 멈춘다. 부르기 전에 확인한다
    missing = [article_id for article_id in ids if article_id not in articles]
    if missing:
        raise ValueError(f"없는 기사 ID: {', '.join(missing)}")
    if args.limit is not None:
        ids = ids[: args.limit]

    results = []
    statuses: Counter = Counter()
    scores: Counter = Counter()
    total_tokens, total_cost = Tokens(), 0.0
    print(f"{len(ids)}건 · 정답 {'있음' if labels else '없음'} · 결과는 끝나고 파일로 남긴다\n")
    for n, article_id in enumerate(ids, start=1):
        article = articles[article_id]
        run = await extract_events(article.get("body"), article.get("title", ""), model=args.model)
        tokens, cost = tokens_of(run.usage), cost_usd(run.usage)
        total_tokens, total_cost = total_tokens + tokens, total_cost + cost
        statuses[run.status] += 1

        label = labels.get(article_id)
        verdict = score(run.events, label) if label and run.status == "ok" else None
        if verdict:
            scores[(bool(label.gold), verdict)] += 1
        stock = label.stock if label else article.get("stock", "")
        print(f"[{n:>2}/{len(ids)}] {article_id} {stock:<10} {run.status:<7} "
              f"사건 {len(run.events):>2}  {('정답 ' + verdict) if verdict else '':<9}  "
              f"{tokens_line(tokens)}  ${cost:.5f}")
        if run.error:
            print(f"        오류 {run.error[:200]}")

        results.append({
            "id": article_id,
            "title": article.get("title"),
            "label": {"kind": label.kind, "stock": label.stock, "gold": sorted(label.gold),
                      "memo": label.memo, "reason": label.reason} if label else None,
            "verdict": verdict,
            "tokens": asdict(tokens),
            "cost_usd": cost,
            "run": asdict(run),
        })

    print("\n=== 합계 ===")
    print("상태 " + ", ".join(f"{k} {v}" for k, v in statuses.items()))
    with_cause = sum(v for (has, _), v in scores.items() if has)
    no_cause = sum(v for (has, _), v in scores.items() if not has)
    if with_cause:
        print(f"원인 있는 기사 {with_cause}건: 전부 담음 {scores[(True, 'all')]} · "
              f"일부 {scores[(True, 'some')]} · 못 담음 {scores[(True, 'none')]}")
    if no_cause:
        print(f"원인 없는 기사 {no_cause}건: 걸러냄 {scores[(False, 'pass')]} · "
              f"그 종목 근거를 냄 {scores[(False, 'fail')]}")
    count = max(len(ids), 1)
    print(f"토큰 {tokens_line(total_tokens)}  (기사당 평균 {total_tokens.total // count:,})")
    print(f"비용 ${total_cost:.5f}  (기사당 평균 ${total_cost / count:.5f})")

    out = args.out or args.articles.parent / f"classify_{datetime.now(KST):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({
        "model": results[0]["run"]["model"] if results else None,
        "prompt_sha256": results[0]["run"]["prompt_sha256"] if results else None,
        "total_tokens": asdict(total_tokens),
        "total_cost_usd": total_cost,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 파일 {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="사건 추출을 돌려 본다")
    parser.add_argument("file", type=Path, nargs="?", help="본문 텍스트 파일(UTF-8). 기사 하나")
    parser.add_argument("--title", default="")
    parser.add_argument("--basis", type=Path, default=None, help="분류 기준 JSON. 기사 하나일 때 연결을 보여 준다")
    parser.add_argument("--articles", type=Path, default=None, help="실험 기사 묶음 articles.json")
    parser.add_argument("--limit", type=int, default=None, help="앞에서 몇 건만")
    parser.add_argument("--ids", default=None, help="쉼표로 구분한 기사 id")
    parser.add_argument("--out", type=Path, default=None, help="묶음 결과 파일 경로")
    parser.add_argument("--review", type=Path, default=None,
                        help="묶음 결과 파일(classify_*.json)로 검토표 CSV 만 만든다. --articles 와 함께")
    parser.add_argument("--model", default=None, help="비우면 설정의 SUMMARY_MODEL")
    args = parser.parse_args()
    if bool(args.file) == bool(args.articles):
        parser.error("기사 파일 하나 또는 --articles 중 하나만 준다")
    if args.limit is not None and args.limit < 1:
        # 0 이 '제한 없음' 으로 읽히면 묶음 전체를 부른다
        parser.error("--limit 은 1 이상이어야 한다")
    if args.review:
        if not args.articles:
            parser.error("--review 는 --articles 와 함께 준다 (문장 원문을 거기서 읽는다)")
        result = json.loads(args.review.read_text(encoding="utf-8"))
        articles = json.loads(args.articles.read_text(encoding="utf-8"))
        out = args.out or args.review.with_name(args.review.name.replace("classify_", "review_", 1)
                                               ).with_suffix(".csv")
        labels_path = args.articles.parent / "labels.csv"
        labels = load_labels(labels_path) if labels_path.is_file() else None
        count = write_review(result, articles, out, labels)
        print(f"검토표 {count}행 → {out}")
        return
    asyncio.run(run_batch(args) if args.articles else run_one(args))


if __name__ == "__main__":
    main()
