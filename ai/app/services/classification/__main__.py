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
    … run --since 2026-11-06 --per-stock-cap 20 --daily-budget 1500
                                           # 네이버 뉴스는 날마다 종목당 20건만, 오늘 비용 ₩1,500 까지
                                           # (.env 의 CLASSIFICATION_PER_STOCK_CAP·DAILY_BUDGET 이 기본값)
                                           # --ids 없는 run 은 한 번에 하나만 돈다. 나중 실행은 기다린다
    uv run python -m app.services.classification show 005930 --days 3
                                           # 종목 하나의 판정 자료·공통 배경 (생성 쪽에 넘기는 것)

run 은 failed 카드가 1건이라도 있으면 끝까지 돈 뒤 exit 1 로 끝난다. no_body·skipped 는 실패가 아니라 exit 0 이다.

DB 를 쓰지 않는 명령 — 프롬프트·모델을 바꿔 가며 볼 때
    uv run python -m app.services.classification try 기사.txt --title "제목"
    uv run python -m app.services.classification eval --articles eval_data/news_compare_tg/articles.json
    … eval --articles … --limit 3 --judge-model <모델>
    … eval --articles … --review eval_data/news_compare_tg/classify_<시각>.json   # 검토표 CSV 만

eval 은 같은 폴더에 labels.csv 가 있으면 정답과 대조해 두 점수를 따로 낸다(evaluate.py).
문장 재현율은 ① 추출만, 종목 연결은 정답 종목 판정(④)까지 본다. 결과는
articles.json 옆에 classify_<시각>.json 으로 남는다(eval_data 는 git 에 안 올라간다).

단계별 모델은 --extract-model / --link-model / --judge-model, 안 주면 .env 의
CLASSIFICATION_<단계>_MODEL, 그것도 없으면 SUMMARY_MODEL 이다(llm.py). LLM 은 .env 의 프로바이더로 부른다.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from contextlib import suppress
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.scope import KST
from app.llm.client import cost_currency, endpoint, format_cost
from app.repositories.classification import (
    DEFAULT_LABELS,
    cards_to_classify,
    classification_cost_since,
    classified_sources,
    naver_news_days,
    save_run,
    stored_basis_versions,
    sync_basis,
)
from app.repositories.scope import collection_locks
from app.repositories.source_card import get_sources
from app.services.classification import splitter
from app.services.classification.basis import Basis, BasisError, load_basis
from app.services.classification.evaluate import (
    load_labels,
    sentence_recall,
    stock_linked,
    write_review,
)
from app.services.classification.judge import LABELS
from app.services.classification.pipeline import ClassificationResult, classify
from app.services.classification.selection import DailyBudget, order_for_classification

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


async def run_classify(args: argparse.Namespace) -> int:
    """카드를 분류해 회차로 저장한다. failed 카드 수를 돌려준다(main 이 1건 이상이면 exit 1).

    no_body·skipped 는 실패가 아니다 — 분류할 본문이 없거나 상한을 넘은 자료라 다시 돌려도 같다.
    """
    basis = load_basis(args.basis)
    endpoint()  # 키가 없으면 자료를 읽기 전에 멈춘다
    # --ids 는 직접 고른 자료라 막지 않는다. 막으면 전체 분류 중에는 모델 비교도 몇 시간씩 멈춘다
    if args.ids is not None:
        return await classify_cards(args, basis)
    print("다른 분류 실행이 있으면 끝날 때까지 기다린다", flush=True)
    # 고르기 전에 잡아 전부 저장할 때까지 쥔다. 회차는 분류 뒤에 생겨서, 겹친 실행은 같은 자료를 또 고른다
    async with collection_locks(SessionLocal, "classification"):
        return await classify_cards(args, basis)


async def classify_cards(args: argparse.Namespace, basis: Basis) -> int:
    """고른 카드를 (동시에) 분류해 저장한다. failed 카드 수를 돌려준다.

    저장(save_run·commit)에 실패하면 롤백하고 그 카드를 failed 회차로 남긴다(쓴 비용 포함). 그 밖의 예상 밖
    예외(본문 읽기 실패 등)는 그 카드만 건너뛰고 error 로 세며, 끝에 SystemExit 로 알린다.
    """
    async with SessionLocal() as session:
        stored = await stored_basis_versions(session)
        if stored != {basis.version}:
            raise SystemExit(
                f"DB 기준표 버전 {sorted(v[:12] for v in stored) or '없음'} 이 기준 파일"
                f" {basis.version[:12]} 과 다르다. 먼저 `basis` 를 돌린다."
            )
        since = datetime.combine(args.since, time(), KST) if args.since else None
        # 비용 장치는 --ids 없는 실행에만 건다. --ids 는 사람이 직접 고른 재분류·실험이다
        cap = args.per_stock_cap if args.ids is None else None
        limit = args.daily_budget if args.ids is None else None
        card_ids = await cards_to_classify(session, card_ids=args.ids, since=since,
                                           limit=None if cap else args.limit, retry=args.retry)
        dropped = 0
        if cap:
            naver = await naver_news_days(session, card_ids)
            card_ids, dropped = order_for_classification(card_ids, naver, basis.stocks.values(), cap)
            card_ids = card_ids[:args.limit] if args.limit is not None else card_ids
        today = datetime.combine(datetime.now(KST).date(), time(), KST)
        budget = DailyBudget(limit, await classification_cost_since(session, today) if limit else 0.0)
    print(f"{len(card_ids)}건 · 기준 {basis.version[:12]} · 동시 {args.concurrency}"
          + (" · 실험(현재 회차를 바꾸지 않음)" if args.experiment else ""))
    if cap:
        print(f"종목당 상한 {cap}건: 네이버 뉴스 {dropped}건은 분류하지 않음(원문은 남음)")
    if limit is not None:
        print(f"하루 비용 상한 {format_cost(limit)}: 오늘 이미 {format_cost(budget.spent)}")

    statuses: Counter = Counter()
    total = 0.0
    retries = 0
    done = 0
    save_failures = 0
    started = perf_counter()
    gate = asyncio.Semaphore(args.concurrency)

    async def work(card_id: int) -> None:
        nonlocal total, retries, done, save_failures
        try:
            # 본문을 게이트 안에서 읽는다. 밖에서 읽으면 대기하는 자료의 본문이 전부 메모리에 올라온다
            async with gate:
                # 상한에 닿으면 시작하지 않는다. 회차를 만들지 않으므로 다음 실행(다음 날)에 다시 고른다
                if not budget.allows():
                    statuses["budget"] += 1
                    return
                async with SessionLocal() as session:
                    records = await get_sources(session, [card_id], include_body=True)
                if not records:
                    return
                record = records[0]
                result = await classify(record.title, record.body if record.has_body else None,
                                        basis, models=models_of(args))
                # 저장에 실패해도 이미 쓴 비용과 재시도는 합계에 남긴다
                total += result.cost
                budget.add(result.cost)
                retries += result.rate_limit_retries
                try:
                    run_id = await _save(card_id, result, make_current=not args.experiment)
                # 카드 하나의 저장 실패로 run 전체가 멈추면 앞에서 쓴 LLM 비용과 뒤 카드가 모두 날아간다.
                # 롤백한 뒤 이 카드를 failed 회차로 남기고(비용 포함) 다음 카드로 넘어간다
                except Exception as exc:  # noqa: BLE001 — 저장 실패의 종류는 error 칸에 남긴다
                    save_failures += 1
                    result = failed_on_save(result, exc)
                    run_id = await _record_save_failure(card_id, result)
            direct = ",".join(basis.stocks[c].name for c in sorted(result.direct_stocks())) or "-"
        except Exception as exc:  # noqa: BLE001 — 한 건 때문에 몇 시간짜리 실행이 멈추지 않게 한다
            # 저장 전(본문 읽기·분류 중)이면 회차가 없어 다시 돌릴 때 또 고른다
            statuses["error"] += 1
            done += 1
            print(f"[{done:>3}/{len(card_ids)}] 자료 {card_id:<7} 오류 "
                  f"{type(exc).__name__}: {str(exc)[:200]}", flush=True)
            return
        statuses[result.status] += 1
        done += 1
        print(f"[{done:>3}/{len(card_ids)}] 자료 {card_id:<7} {record.kind:<8} {result.status:<8} "
              f"회차 {'-' if run_id is None else run_id:<6} 사건 {len(result.events):>2}  DIRECT {direct}  "
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
        if statuses["budget"]:
            print(f"하루 비용 상한에 닿아 {statuses['budget']}건은 시작하지 않음"
                  f" (오늘 {format_cost(budget.spent)} / 상한 {format_cost(budget.limit)})")
    # 하루 상한으로 시작하지 않은 자료는 failed 가 아니다. 다음 실행에서 다시 고른다
    failed = statuses["failed"]
    if failed:
        # 자동화가 알아채도록 종료 코드로도 알린다(main). 사유는 위의 카드별 「오류」 줄과 classification_runs.error
        print(f"실패 {failed}건 (그중 저장 실패 {save_failures}건) — 종료 코드 1. "
              "`run --retry` 로 다시 분류한다")
    else:
        print("실패 0건")
    if statuses["error"]:
        raise SystemExit(f"오류 {statuses['error']}건. 위 오류 줄을 확인한다")
    return failed


async def _save(card_id: int, result: ClassificationResult, *, make_current: bool) -> int:
    """회차 하나를 저장하고 커밋한다. 실패하면 롤백하고 예외를 올린다."""
    async with SessionLocal() as session:
        try:
            run_id = await save_run(session, card_id, result, make_current=make_current)
            await session.commit()
        except BaseException:
            # 연결이 끊겼으면 롤백도 실패한다. 원래 예외를 가리지 않게 롤백 실패는 넘긴다
            with suppress(Exception):
                await session.rollback()
            raise
    return run_id


def failed_on_save(result: ClassificationResult, exc: Exception) -> ClassificationResult:
    """저장에 실패한 결과를 failed 회차로 바꾼다. 사건은 버리고 단계별 호출(사용량·비용·응답 원문)은 남긴다."""
    error = f"save_failed: {type(exc).__name__}: {str(exc)[:300]}"
    if result.error:
        error += f" (분류 결과 {result.status}: {result.error[:200]})"
    return replace(result, status="failed", events=[], error=error)


async def _record_save_failure(card_id: int, result: ClassificationResult) -> int | None:
    """failed 회차를 남긴다. 이것마저 실패하면(DB 가 내려감 등) 회차 없이 넘어가고 None."""
    print(f"        저장 실패 — {result.error[:200]}")
    try:
        return await _save(card_id, result, make_current=False)
    except Exception as exc:  # noqa: BLE001 — 기록마저 못 하면 화면에만 남기고 다음 카드로 간다
        print(f"        failed 회차도 남기지 못함 — {type(exc).__name__}: {str(exc)[:200]}")
        return None


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


def _score_lines(title: str, scores: Counter) -> list[str]:
    """채점 하나의 합계. scores 의 키는 (원인 있는 기사인가, 판정)."""
    with_cause = sum(v for (has, _), v in scores.items() if has)
    no_cause = sum(v for (has, _), v in scores.items() if not has)
    if not with_cause and not no_cause:
        return []
    lines = [title]
    if with_cause:
        lines.append(f"  원인 있는 기사 {with_cause}건: 전부 담음 {scores[(True, 'all')]} · "
                     f"일부 {scores[(True, 'some')]} · 못 담음 {scores[(True, 'none')]}")
    if no_cause:
        lines.append(f"  원인 없는 기사 {no_cause}건: 걸러냄 {scores[(False, 'pass')]} · "
                     f"그 종목 근거를 냄 {scores[(False, 'fail')]}")
    return lines


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

    results, statuses, total = [], Counter(), 0.0
    recall, linked, out_of_basis = Counter(), Counter(), 0
    print(f"{len(ids)}건 · 정답 {'있음' if labels else '없음'} · 기준 {basis.version[:12]}\n")
    for n, article_id in enumerate(ids, start=1):
        article = articles[article_id]
        result = await classify(article.get("title"), article.get("body"), basis,
                                models=models_of(args))
        statuses[result.status] += 1
        total += result.cost
        label = labels.get(article_id)
        verdict = verdict_linked = None
        if label and result.status == "ok":
            verdict = sentence_recall([i.event for i in result.events], label)
            recall[(bool(label.gold), verdict)] += 1
            verdict_linked = stock_linked(result.events, label, basis)
            if verdict_linked:
                linked[(bool(label.gold), verdict_linked)] += 1
            else:
                out_of_basis += 1
        graded = (f"문장 {verdict} · 연결 {verdict_linked or '기준 밖'}" if verdict else "")
        direct = ",".join(basis.stocks[c].name for c in sorted(result.direct_stocks())) or "-"
        print(f"[{n:>2}/{len(ids)}] {article_id} {result.status:<7} 사건 {len(result.events):>2}  "
              f"{graded:<22} DIRECT {direct}  {format_cost(result.cost)}")
        if result.error:
            print(f"        오류 {result.error[:200]}")
        results.append({
            "id": article_id, "title": article.get("title"),
            "label": {"kind": label.kind, "stock": label.stock, "gold": sorted(label.gold),
                      "memo": label.memo, "reason": label.reason} if label else None,
            "verdict": verdict, "verdict_linked": verdict_linked,
            "cost": result.cost, "run": result_dict(result),
        })

    print("\n=== 합계 ===")
    print("상태 " + ", ".join(f"{k} {v}" for k, v in statuses.items()))
    # 두 점수는 다른 단계를 잰다. 합치지 않고 따로 찍는다(evaluate.py)
    for line in _score_lines("문장 재현율 (① 추출: 어느 사건이든 정답 문장을 덮었나)", recall):
        print(line)
    for line in _score_lines("종목 연결 (①~④: 정답 종목에 붙은 사건이 정답 문장을 덮었나)", linked):
        print(line)
    if out_of_basis:
        print(f"  정답 종목이 기준 밖이라 종목 연결을 못 잰 기사 {out_of_basis}건")
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
    run.add_argument("--per-stock-cap", type=int, default=settings.classification_per_stock_cap,
                     help="날마다 종목당 네이버 뉴스 상한. 비우면 .env 의 CLASSIFICATION_PER_STOCK_CAP."
                          " 0 이면 걸지 않는다. --ids 에는 걸지 않는다")
    run.add_argument("--daily-budget", type=float, default=settings.classification_daily_budget,
                     help="오늘(KST) 분류 비용 상한. 비우면 .env 의 CLASSIFICATION_DAILY_BUDGET."
                          " --ids 에는 걸지 않는다")
    add_models(run)

    show = sub.add_parser("show", help="종목 하나에 붙는 분류 자료를 본다")
    show.add_argument("stock", help="종목코드 6자리")
    show.add_argument("--until", default=None, help="기준 시각 ISO 8601. 비우면 지금")
    show.add_argument("--days", type=int, default=3, help="기준 시각에서 며칠 전까지")
    show.add_argument("--labels", nargs="+", default=list(DEFAULT_LABELS), choices=LABELS)

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
            # failed 카드가 1건이라도 있으면 끝까지 돈 뒤 exit 1. no_body·skipped 는 실패가 아니다
            if asyncio.run(run_classify(args)):
                raise SystemExit(1)
        elif args.command == "show":
            asyncio.run(run_show(args))
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
