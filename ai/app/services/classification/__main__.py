"""자료 분류 실행. 단계는 pipeline.py, 저장·조회는 repositories/classification.py 다.

DB 에 쓰는 명령
    uv run python -m app.services.classification basis             # 기준 JSON → 기준표 (검사 후 넣는다)
    uv run python -m app.services.classification basis --check     # 검사만
    uv run python -m app.services.classification run --limit 20    # 회차가 없는 자료를 최근 것부터
    … run --since 2026-10-28 --retry       # 그날 이후 자료. 실패·본문 없음만 있는 자료도 다시
    … run --ids 101 102                    # 이 자료만 (회차가 있어도 새 회차를 만든다)
    … run --ids 101 --experiment --judge-model <모델>
                                           # 저장하되 조회에 쓰는 회차는 바꾸지 않는다(모델 비교)
    … run --limit 20 --concurrency 8       # 자료 8건을 동시에. 비용은 같고 시간만 준다
                                           # --ids 없는 run 은 한 번에 하나만 돈다. 나중 실행은 기다린다
    uv run python -m app.services.classification show 005930 --days 3
                                           # 종목 하나의 판정 자료·공통 배경 (생성 쪽에 넘기는 것)
    uv run python -m app.services.classification same-event --since 2026-11-01 --limit 200
                                           # 분류가 끝난 사건을 같은 사건끼리 묶는다
    … same-event --since 2026-11-01 --limit 200 --dry-run   # 저장하지 않고 결과와 비용만 (LLM 은 부른다)
                                           # same-event 는 한 번에 하나만 돈다. 나중 실행은 기다린다

DB 를 쓰지 않는 명령 — 프롬프트·모델을 바꿔 가며 볼 때
    uv run python -m app.services.classification try 기사.txt --title "제목"
    uv run python -m app.services.classification eval --articles eval_data/news_compare_tg/articles.json
    … eval --articles … --limit 3 --judge-model <모델>
    … eval --articles … --review eval_data/news_compare_tg/classify_<시각>.json   # 검토표 CSV 만

eval 은 같은 폴더에 labels.csv 가 있으면 ① 추출을 정답 문장과 대조한다(evaluate.py). 결과는
articles.json 옆에 classify_<시각>.json 으로 남는다(eval_data 는 git 에 안 올라간다).

단계별 모델은 --extract-model / --link-model / --judge-model, 안 주면 .env 의
CLASSIFICATION_<단계>_MODEL, 그것도 없으면 SUMMARY_MODEL 이다(llm.py). LLM 은 .env 의 프로바이더로 부른다.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter

from app.core.database import SessionLocal
from app.core.scope import KST
from app.llm.client import cost_currency, endpoint, format_cost
from app.repositories.classification import (
    DEFAULT_LABELS,
    cards_to_classify,
    classified_sources,
    save_run,
    stored_basis_versions,
    sync_basis,
)
from app.repositories.scope import collection_locks
from app.repositories.source_card import get_sources
from app.services.classification import splitter
from app.services.classification.basis import Basis, BasisError, load_basis
from app.services.classification.evaluate import load_labels, score, write_review
from app.services.classification.judge import LABELS
from app.services.classification.pipeline import ClassificationResult, classify
from app.services.classification.same_event_run import run_same_event

# ── 출력 ─────────────────────────────────────────────────────────────────


def describe(result: ClassificationResult, body: str, basis: Basis) -> list[str]:
    """결과를 사람이 읽는 줄로. try 와 eval 이 쓴다."""
    lines = [f"상태 {result.status}  문장 {result.sentence_count}  비용 {format_cost(result.cost)}"]
    lines += [f"  {step}: {call.model}" for step, call in result.calls.items()]
    if result.error:
        lines.append(f"오류 {result.error}")
    if result.status != "ok":
        return lines
    if not result.events:
        lines.append("사건 없음 — 이유가 될 내용이 없는 자료로 판단")
    sentences = splitter.split(body, result.splitter_version)
    for item in result.events:
        e = item.event
        lines.append(f"\n[{e.order_index}] {e.scope} / {e.role} / {e.tense}  "
                     f"문장 {list(e.sentence_indices)}  문맥 {list(e.context_indices)}")
        lines += [f"    {i}. {sentences[i - 1]}" + ("  (문맥)" if i in e.context_indices else "")
                  for i in (*e.context_indices, *e.sentence_indices)]
        linked = [f"{link.mention}→{link.stock_code or link.industry_code or link.external_code}"
                  + (f"(자회사 {link.via_subsidiary})" if link.via_subsidiary else "")
                  + ("*" if link.linked_by == "llm_code" else "") for link in item.links]
        lines.append(f"    연결 {linked}  미연결 {item.unresolved}")
        judgments = {j.stock_code: j for j in item.judgments}
        for c in item.candidates:
            j = judgments.get(c.stock_code)
            via = c.industry_code or c.via_stock_code or c.via_external_code or ""
            lines.append(f"    {basis.stocks[c.stock_code].name:<10} {c.path:<8} {via:<14} "
                         f"{j.label if j else '-':<16} {j.reason if j else ''}")
    if any(result.judge_fixes.values()):
        lines.append(f"\n판정 보정 {result.judge_fixes}")
    if result.dropped_mentions:
        lines.append(f"원문에 없어 뺀 표기 {result.dropped_mentions}")
    return lines


def result_dict(result: ClassificationResult) -> dict:
    """eval 결과 파일에 남기는 모양. 검토표(write_review)가 읽는 칸(run.status·events 등)을 지킨다."""
    calls = {step: {"model": c.model, "raw_response": c.raw_response, "error": c.error}
             for step, c in result.calls.items()}
    return {
        "status": result.status, "error": result.error, "basis_version": result.basis_version,
        "splitter_version": result.splitter_version, "sentence_count": result.sentence_count,
        "raw_response": calls.get("extract", {}).get("raw_response"),
        "calls": calls, "usage": result.usage, "judge_fixes": result.judge_fixes,
        "dropped_mentions": result.dropped_mentions,
        "events": [{
            **asdict(item.event),
            "links": [asdict(link) for link in item.links], "unresolved": item.unresolved,
            "candidates": [{k: v for k, v in asdict(c).items() if k != "link"}
                           for c in item.candidates],
            "judgments": [asdict(j) for j in item.judgments],
        } for item in result.events],
    }


def models_of(args: argparse.Namespace) -> dict[str, str | None]:
    return {"extract": args.extract_model, "link": args.link_model, "judge": args.judge_model}


# ── DB 명령 ──────────────────────────────────────────────────────────────


async def run_basis(path: Path | None, check_only: bool) -> None:
    basis = load_basis(path)
    print(f"기준 {basis.name}  버전 {basis.version[:12]}")
    print(f"산업 {len(basis.industries)} · 종목 {len(basis.stocks)} · 외부 기업 {len(basis.externals)}"
          f" · 종목–산업 {len(basis.stock_industries)} · 기업 관계 {len(basis.relations)}")
    if check_only:
        return
    async with SessionLocal() as session:
        counts = await sync_basis(session, basis)
        await session.commit()
    print("넣음 " + ", ".join(f"{k} {v}" for k, v in counts.items()))


async def run_classify(args: argparse.Namespace) -> None:
    basis = load_basis(args.basis)
    endpoint()  # 키가 없으면 자료를 읽기 전에 멈춘다
    # --ids 는 직접 고른 자료라 막지 않는다. 막으면 전체 분류 중에는 모델 비교도 몇 시간씩 멈춘다
    if args.ids is not None:
        await classify_cards(args, basis)
        return
    print("다른 분류 실행이 있으면 끝날 때까지 기다린다", flush=True)
    # 고르기 전에 잡아 전부 저장할 때까지 쥔다. 회차는 분류 뒤에 생겨서, 겹친 실행은 같은 자료를 또 고른다
    async with collection_locks(SessionLocal, "classification"):
        await classify_cards(args, basis)


async def classify_cards(args: argparse.Namespace, basis: Basis) -> None:
    async with SessionLocal() as session:
        stored = await stored_basis_versions(session)
        if stored != {basis.version}:
            raise SystemExit(
                f"DB 기준표 버전 {sorted(v[:12] for v in stored) or '없음'} 이 기준 파일"
                f" {basis.version[:12]} 과 다르다. 먼저 `basis` 를 돌린다."
            )
        since = datetime.combine(args.since, time(), KST) if args.since else None
        card_ids = await cards_to_classify(session, card_ids=args.ids, since=since,
                                           limit=args.limit, retry=args.retry)
    print(f"{len(card_ids)}건 · 기준 {basis.version[:12]} · 동시 {args.concurrency}"
          + (" · 실험(현재 회차를 바꾸지 않음)" if args.experiment else ""))

    statuses: Counter = Counter()
    total = 0.0
    retries = 0
    done = 0
    started = perf_counter()
    gate = asyncio.Semaphore(args.concurrency)

    async def work(card_id: int) -> None:
        nonlocal total, retries, done
        try:
            # 본문을 게이트 안에서 읽는다. 밖에서 읽으면 대기하는 자료의 본문이 전부 메모리에 올라온다
            async with gate:
                async with SessionLocal() as session:
                    records = await get_sources(session, [card_id], include_body=True)
                if not records:
                    return
                record = records[0]
                result = await classify(record.title, record.body if record.has_body else None,
                                        basis, models=models_of(args))
                # 저장에 실패해도 이미 쓴 비용과 재시도는 합계에 남긴다
                total += result.cost
                retries += result.rate_limit_retries
                async with SessionLocal() as session:
                    run_id = await save_run(session, card_id, result,
                                            make_current=not args.experiment)
                    await session.commit()
            direct = ",".join(basis.stocks[c].name for c in sorted(result.direct_stocks())) or "-"
        except Exception as exc:  # noqa: BLE001 — 한 건 때문에 몇 시간짜리 실행이 멈추지 않게 한다
            # 저장 전이면 회차가 없어 다시 돌릴 때 또 고른다
            statuses["error"] += 1
            done += 1
            print(f"[{done:>3}/{len(card_ids)}] 자료 {card_id:<7} 오류 "
                  f"{type(exc).__name__}: {str(exc)[:200]}", flush=True)
            return
        statuses[result.status] += 1
        done += 1
        print(f"[{done:>3}/{len(card_ids)}] 자료 {card_id:<7} {record.kind:<8} {result.status:<8} "
              f"회차 {run_id:<6} 사건 {len(result.events):>2}  DIRECT {direct}  "
              f"{format_cost(result.cost)}", flush=True)
        if result.error:
            print(f"        오류 {result.error[:200]}", flush=True)

    try:
        await asyncio.gather(*(work(card_id) for card_id in card_ids))
    finally:
        # Ctrl+C 로 멈춰도 그때까지 쓴 비용을 남긴다
        print("\n상태 " + (", ".join(f"{k} {v}" for k, v in statuses.items()) or "없음")
              + f"  비용 {format_cost(total)}  429 재시도 {retries}회"
              + f"  소요 {perf_counter() - started:,.0f}초")
    if statuses["error"]:
        raise SystemExit(f"오류 {statuses['error']}건. 위 오류 줄을 확인한다")


async def run_show(args: argparse.Namespace) -> None:
    until = datetime.fromisoformat(args.until) if args.until else datetime.now(KST)
    if until.tzinfo is None:
        until = until.replace(tzinfo=KST)
    since = until - timedelta(days=args.days)
    async with SessionLocal() as session:
        found = await classified_sources(session, args.stock, until=until, since=since,
                                         labels=tuple(args.labels))
    print(f"{args.stock}  {since:%Y-%m-%d %H:%M} ~ {until:%Y-%m-%d %H:%M}  판정 {args.labels}")
    for source in found["sources"]:
        paths = Counter(e["path"] for e in source["events"])
        print(f"  자료 {source['source_card_id']:<7} {source['card_type']:<8} "
              f"{source['card_label'] or '공통 배경':<17} {source['available_at'] or '-':<26} "
              f"{dict(paths)}  {source['source_name'] or ''}")
    print(f"자료 {len(found['sources'])} · 미분류 {found['unclassified']} · 실패 {found['failed']}"
          f" · 기준 시각 뒤 본문 {found['not_observed']}")


# ── DB 를 쓰지 않는 명령 ──────────────────────────────────────────────────


async def run_try(args: argparse.Namespace) -> None:
    basis = load_basis(args.basis)
    body = args.file.read_text(encoding="utf-8")
    result = await classify(args.title, body, basis, models=models_of(args))
    print("\n".join(describe(result, body, basis)))


async def run_eval(args: argparse.Namespace) -> None:
    basis = load_basis(args.basis)
    articles: dict = json.loads(args.articles.read_text(encoding="utf-8"))
    labels_path = args.articles.parent / "labels.csv"
    labels = load_labels(labels_path) if labels_path.is_file() else {}
    ids = (list(dict.fromkeys(i.strip() for i in args.ids.split(",") if i.strip()))
           if args.ids else list(articles))
    # 오타 난 id 가 섞이면 앞 기사들에 비용을 쓴 뒤에야 멈춘다. 부르기 전에 확인한다
    missing = [article_id for article_id in ids if article_id not in articles]
    if missing:
        raise SystemExit(f"없는 기사 ID: {', '.join(missing)}")
    ids = ids[: args.limit] if args.limit else ids
    endpoint()

    results, statuses, scores, total = [], Counter(), Counter(), 0.0
    print(f"{len(ids)}건 · 정답 {'있음' if labels else '없음'} · 기준 {basis.version[:12]}\n")
    for n, article_id in enumerate(ids, start=1):
        article = articles[article_id]
        result = await classify(article.get("title"), article.get("body"), basis,
                                models=models_of(args))
        statuses[result.status] += 1
        total += result.cost
        label = labels.get(article_id)
        verdict = (score([i.event for i in result.events], label)
                   if label and result.status == "ok" else None)
        if verdict:
            scores[(bool(label.gold), verdict)] += 1
        direct = ",".join(basis.stocks[c].name for c in sorted(result.direct_stocks())) or "-"
        print(f"[{n:>2}/{len(ids)}] {article_id} {result.status:<7} 사건 {len(result.events):>2}  "
              f"{('정답 ' + verdict) if verdict else '':<9} DIRECT {direct}  {format_cost(result.cost)}")
        if result.error:
            print(f"        오류 {result.error[:200]}")
        results.append({
            "id": article_id, "title": article.get("title"),
            "label": {"kind": label.kind, "stock": label.stock, "gold": sorted(label.gold),
                      "memo": label.memo, "reason": label.reason} if label else None,
            "verdict": verdict, "cost": result.cost, "run": result_dict(result),
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
    print(f"비용 {format_cost(total)} (기사당 평균 {format_cost(total / max(len(ids), 1))})")

    out = args.out or args.articles.parent / f"classify_{datetime.now(KST):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({
        "models": {step: call["model"] for step, call in
                   (results[0]["run"]["calls"].items() if results else [])},
        "basis_version": basis.version, "cost_currency": cost_currency(), "total_cost": total,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 파일 {out}")


def write_review_only(args: argparse.Namespace) -> None:
    result = json.loads(args.review.read_text(encoding="utf-8"))
    articles = json.loads(args.articles.read_text(encoding="utf-8"))
    out = args.out or args.review.with_name(
        args.review.name.replace("classify_", "review_", 1)).with_suffix(".csv")
    labels_path = args.articles.parent / "labels.csv"
    labels = load_labels(labels_path) if labels_path.is_file() else None
    print(f"검토표 {write_review(result, articles, out, labels)}행 → {out}")


# ── 인자 ─────────────────────────────────────────────────────────────────


def _date(text: str) -> date:
    return date.fromisoformat(text)


def main() -> None:
    # 한국어 Windows 콘솔(cp949)에서 '—' 같은 글자를 찍다가 죽지 않게 한다
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="자료 분류")
    sub = parser.add_subparsers(dest="command", required=True)

    basis = sub.add_parser("basis", help="기준 JSON 을 검사하고 기준표에 넣는다")
    basis.add_argument("--file", type=Path, default=None, help="비우면 기준 폴더의 마지막 파일")
    basis.add_argument("--check", action="store_true", help="검사만 하고 DB 에 넣지 않는다")

    def add_models(p: argparse.ArgumentParser) -> None:
        p.add_argument("--basis", type=Path, default=None, help="기준 JSON. 비우면 기준 폴더의 마지막 파일")
        p.add_argument("--extract-model", default=None)
        p.add_argument("--link-model", default=None)
        p.add_argument("--judge-model", default=None)

    run = sub.add_parser("run", help="자료를 분류해 회차로 저장한다")
    run.add_argument("--ids", type=int, nargs="+", default=None, help="공통 자료 ID. 회차가 있어도 다시")
    run.add_argument("--since", type=_date, default=None, help="이 날짜(KST) 이후 자료")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--retry", action="store_true", help="현재 회차가 없는 자료(실패 등)도 다시")
    run.add_argument("--experiment", action="store_true",
                     help="저장만 하고 조회에 쓰는 회차를 바꾸지 않는다")
    run.add_argument("--concurrency", type=int, default=1,
                     help="동시에 분류할 자료 수. 8 까지 재 봤다. 429 로그가 자주 보이면 낮춘다")
    add_models(run)

    show = sub.add_parser("show", help="종목 하나에 붙는 분류 자료를 본다")
    show.add_argument("stock", help="종목코드 6자리")
    show.add_argument("--until", default=None, help="기준 시각 ISO 8601. 비우면 지금")
    show.add_argument("--days", type=int, default=3, help="기준 시각에서 며칠 전까지")
    show.add_argument("--labels", nargs="+", default=list(DEFAULT_LABELS), choices=LABELS)

    same_event = sub.add_parser("same-event", help="분류가 끝난 사건을 같은 사건끼리 묶는다")
    same_event.add_argument("--since", type=_date, default=None, help="이 날짜(KST) 이후 자료")
    same_event.add_argument("--limit", type=int, default=None, help="이번에 처리할 자료 수")
    same_event.add_argument("--dry-run", action="store_true",
                            help="저장하지 않고 결과와 비용만 본다. LLM 비용은 든다")

    try_parser = sub.add_parser("try", help="본문 파일 하나를 분류해 본다 (DB 안 씀)")
    try_parser.add_argument("file", type=Path)
    try_parser.add_argument("--title", default="")
    add_models(try_parser)

    eval_parser = sub.add_parser("eval", help="실험 기사 묶음을 분류해 본다 (DB 안 씀)")
    eval_parser.add_argument("--articles", type=Path, required=True)
    eval_parser.add_argument("--limit", type=int, default=None)
    eval_parser.add_argument("--ids", default=None, help="쉼표로 구분한 기사 id")
    eval_parser.add_argument("--out", type=Path, default=None)
    eval_parser.add_argument("--review", type=Path, default=None,
                             help="결과 파일(classify_*.json)로 검토표 CSV 만 만든다")
    add_models(eval_parser)

    args = parser.parse_args()
    if getattr(args, "limit", None) is not None and args.limit < 1:
        # 0 이 '제한 없음' 으로 읽히면 묶음 전체를 부른다
        parser.error("--limit 은 1 이상이어야 한다")
    if getattr(args, "concurrency", 1) < 1:
        parser.error("--concurrency 는 1 이상이어야 한다")
    try:
        if args.command == "basis":
            asyncio.run(run_basis(args.file, args.check))
        elif args.command == "run":
            asyncio.run(run_classify(args))
        elif args.command == "show":
            asyncio.run(run_show(args))
        elif args.command == "same-event":
            asyncio.run(run_same_event(args.since, args.limit, args.dry_run))
        elif args.command == "try":
            asyncio.run(run_try(args))
        elif args.review:
            write_review_only(args)
        else:
            asyncio.run(run_eval(args))
    except BasisError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
