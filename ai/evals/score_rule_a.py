"""규칙 A 채점. 러너 실행 결과(parsed/)를 gold 사건과 맞춰 link 유무를 코드로 센다. 표준 라이브러리만 쓴다.

    python3 evals/score_rule_a.py --cases evals/cases --run evals/reports/<id>/<runner_run_dir> --out evals/reports/<id>
    python3 evals/score_rule_a.py --cases evals/cases_live --run ... --out ...

규칙 A (2026-11-10 팀 결정):
    gold 사건 강도 coincident            → 보고서에 그 사건 link 가 "없어야" 정답
    gold 사건 강도 likely_cause          → 그 사건 link 가 "있어야" 정답
    gold 사건 강도 possible_contributor  → 둘 다 정답. 있음·없음을 따로 센다
러너가 종목 언급 메시지 link 를 sufficient 로 올리는 것은 의도된 설계라 강도 값은 채점에 쓰지 않고 기록만 한다.

보고서 link → gold 사건 대응:
    0. factor 출처가 모두 그 케이스의 시황·오버나이트 메시지(LEGACY_RECAP_URLS)면 사건에 대응하지 않고 "시황 메시지 link" 로
       따로 센다. 안 A(구형 입력)는 kind 가 없어 이 메시지가 근거 칸에 들어간다. 실서비스에서는 분류 단계에서 걸러질 수 있다
    1. factor 의 sources URL 이 사건 supporting_sources 에 있으면 그 사건(하나라도 맞으면 2 는 보지 않음).
       URL 로 여러 사건이 맞고 그중 factor stance 와 같은 stance 의 사건이 있으면 그 사건만 남긴다
       (같은 메시지에서 호재·악재 대목을 사건 둘로 나눈 경우, 예: c05 e2·e3)
    2. URL 로 맞은 사건이 없으면 그 URL 의 입력 본문이 사건 key_facts 를 모두 "그대로(exact)" 담으면 그 사건.
       fact_match 의 fuzzy(낱말 끝 한 글자를 뗀 부분 일치)는 쓰지 않는다 — "IPO"·"SOX" 가 "IP"·"SO" 로 다른 메시지에
       맞아 c03 에서 엉뚱한 사건이 잡혔다(2026-11-10)
    3. 어느 사건에도 안 맞으면 "gold 밖 link" — 근거 없는 원인(SPURIOUS_CAUSE) 후보로 사람이 확인

대조 link(direction_match=false): 러너 판정(finalize.layer_verdict)은 link 의 direction_match 를 보지 않고 그 층 link 를
모두 센다. 그래서 대조 link 도 규칙 A 위반에 그대로 넣고, 따로 contrast_links 로도 센다(위반 수에서 빼지 않음).

그 밖에 센다: 층별 판정 일치, 시황(market_recap) 메시지를 factor 근거로 쓴 수, cutoff 이후 삽입 자료
(provenance injected_after_cutoff) 인용 수, LLM 없이 낸 정형 보고서 수, 3회 결론 일치.
의미 판단(과장 문장, 출처 정확성)은 여기서 하지 않는다. validate_gold.py·lock_set.py 는 바꾸지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validate_gold import fact_match  # noqa: E402  같은 대조 규칙을 쓴다

LAYERS = ("move", "relative")
# 케이스별 시황·오버나이트 메시지. gold 사건이 아니고 notes.md 에 적어 둠(2026-11-10). 이 메시지만 인용한 link 는 따로 센다
LEGACY_RECAP_URLS = {
    "c07_005930_2026-10-26": {"https://t.me/merITz_tech/19185"},
    "c09_009150_2026-10-28": {"https://t.me/KISGregKim/18879"},
}
VERDICT_KEYS = {"move": "verdict", "relative": "relative_verdict"}


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def case_index(root: Path) -> dict[tuple[str, str], Path]:
    out = {}
    for d in sorted(root.iterdir()):
        if (d / "gold.json").exists() and (d / "case.json").exists():
            c = load(d / "case.json")
            out[(str(c["code"]), c["target_date"])] = d
    return out


def report_of(w: dict):
    text = w.get("final_text")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def factor_events(factor: dict, events: list[dict], texts: dict[str, str]) -> tuple[set[str], list[str]]:
    """(대응한 사건 id, 대응 근거 설명)."""
    hit, why = set(), []
    urls = [s.get("url") for s in factor.get("sources") or [] if s.get("url")]
    for e in events:
        sup = {s["url"] if isinstance(s, dict) else s for s in e.get("supporting_sources") or []}
        if sup & set(urls):
            hit.add(e["id"]); why.append(f"{e['id']}: supporting_sources URL")
    stance = factor.get("stance")
    same = {e["id"] for e in events if e["id"] in hit and e.get("stance") == stance}
    if len(hit) > 1 and same and same != hit:
        why.append(f"stance {stance} 로 좁힘: {sorted(hit)} → {sorted(same)}")
        hit = same
    # URL 로 맞은 사건이 있으면 key_facts 대조는 하지 않는다. 한 factor 에 섞인 다른 메시지가 넓은 key_facts 로
    # 다른 사건(예: 실적 전 기대)까지 끌어오지 않게 한다
    if hit:
        return hit, why
    for e in events:
        facts = [f for f in e.get("key_facts") or [] if f.strip()]
        if not facts:
            continue
        for u in urls:
            body = texts.get(u)
            if body and all(fact_match(f, body)[0] == "exact" for f in facts):
                hit.add(e["id"]); why.append(f"{e['id']}: {u} 본문이 key_facts 를 담음")
                break
    return hit, why


def score_report(w: dict, case: dict, gold: dict, prov: dict, recap_urls: set[str] = frozenset()) -> dict:
    r = report_of(w)
    out = {"run_id": w.get("run_id"), "verify_status": w.get("verify_status"),
           "skipped_llm": w.get("skipped_llm"), "cost": w.get("cost") or 0.0, "is_error": w.get("is_error")}
    if r is None:
        out["error"] = "보고서 없음"
        return out
    events = gold.get("events") or []
    ev_by_id = {e["id"]: e for e in events}
    msgs = {m["url"]: m for m in case.get("messages", [])}
    texts = {u: m.get("text") or "" for u, m in msgs.items()}
    injected = {x["url"] if isinstance(x, dict) else x for x in prov.get("injected_after_cutoff", [])}

    verdicts = {layer: r.get(VERDICT_KEYS[layer]) for layer in LAYERS}
    exp = gold.get("expected_verdict") or {}
    out["verdict"] = verdicts
    out["verdict_match"] = {layer: verdicts[layer] == exp.get(layer) for layer in LAYERS}

    linked = defaultdict(set)      # 사건 id → link 가 달린 층
    strengths = defaultdict(list)  # 사건 id → (층, 최종 strength)
    extra_links, recap_cited, injected_cited, kinds_cited = [], [], [], Counter()
    recap_msg_links, contrast_links = [], []
    for i, f in enumerate(r.get("factors") or []):
        links = [l for l in f.get("links") or [] if l.get("layer") in LAYERS]
        for s in f.get("sources") or []:
            u = s.get("url")
            kind = (msgs.get(u) or {}).get("kind")
            kinds_cited[kind or ("입력 밖" if u not in msgs else "칸 없음(구형 입력)")] += 1
            if kind == "market_recap" or s.get("is_market_recap"):
                recap_cited.append({"factor": i, "url": u})
            if u in injected:
                injected_cited.append({"factor": i, "url": u})
        if not links:
            continue
        for l in links:
            if l.get("direction_match") is False:
                contrast_links.append({"factor": i, "layer": l["layer"], "event": f.get("event")})
        urls = [s.get("url") for s in f.get("sources") or [] if s.get("url")]
        if urls and recap_urls and set(urls) <= recap_urls:
            recap_msg_links.append({"factor": i, "event": f.get("event"), "urls": urls,
                                    "links": [(l["layer"], l.get("strength")) for l in links]})
            continue
        hit, why = factor_events(f, events, texts)
        for eid in hit:
            for l in links:
                linked[eid].add(l["layer"]); strengths[eid].append((l["layer"], l.get("strength")))
        if not hit:
            extra_links.append({"factor": i, "event": f.get("event"),
                                "urls": [s.get("url") for s in f.get("sources") or []],
                                "links": [(l["layer"], l.get("strength")) for l in links]})

    per_event, viol, pc = [], [], Counter()
    for e in events:
        eid, cap = e["id"], e.get("max_causal_strength")
        layers = linked.get(eid, set())
        want_layers = set(e.get("layer") or []) or set(LAYERS)
        is_linked = bool(layers)
        if cap == "coincident":
            ok, rule = not is_linked, "link 없음이 정답"
        elif cap == "likely_cause":
            ok, rule = bool(layers & want_layers), "link 있음이 정답"
        else:
            ok, rule = True, "둘 다 허용"
            pc["linked" if is_linked else "unlinked"] += 1
        item = {"id": eid, "importance": e.get("importance"), "cap": cap, "linked_layers": sorted(layers),
                "strengths": strengths.get(eid, []), "rule": rule, "ok": ok}
        per_event.append(item)
        if not ok:
            viol.append(item)
    out.update({
        "events": per_event,
        "rule_a_violations": [{"id": v["id"], "cap": v["cap"], "linked_layers": v["linked_layers"]} for v in viol],
        "rule_a_violation_count": len(viol),
        "overclaim_candidates": sum(1 for v in viol if v["cap"] == "coincident"),
        "omission_candidates": sum(1 for v in viol if v["cap"] == "likely_cause"),
        "possible_contributor": dict(pc),
        "extra_links": extra_links, "spurious_candidates": len(extra_links),
        "recap_msg_links": recap_msg_links, "recap_msg_link_count": len(recap_msg_links),
        "contrast_links": contrast_links, "contrast_link_count": len(contrast_links),
        "recap_cited_as_factor": recap_cited, "injected_cited": injected_cited,
        "factor_source_kinds": dict(kinds_cited),
        "conclusion": {"verdict": verdicts, "linked_events": sorted(linked), "extra": len(extra_links),
                       "recap_msg": len(recap_msg_links)},
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="규칙 A 채점")
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--run", type=Path, required=True, help="러너 실행 디렉터리(parsed/ 가 있는 곳)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    idx = case_index(args.cases)
    by_case: dict[str, list[dict]] = defaultdict(list)
    unmatched = []
    for p in sorted((args.run / "parsed").glob("*.json")):
        w = load(p)
        used = args.run / w["input_used_path"] if w.get("input_used_path") else None
        payload = load(used) if used and used.exists() else None
        key = (str(payload["code"]), payload["target_date"]) if payload else None
        d = idx.get(key)
        if d is None:
            unmatched.append(p.name)
            continue
        case, gold = load(d / "case.json"), load(d / "gold.json")
        prov = load(d / "provenance.json") if (d / "provenance.json").exists() else {}
        by_case[d.name].append(score_report(w, case, gold, prov, LEGACY_RECAP_URLS.get(d.name, set())))

    (args.out / "cases").mkdir(parents=True, exist_ok=True)
    summary = {"cases_root": str(args.cases), "run_dir": str(args.run), "rule": "A", "unmatched_parsed": unmatched, "cases": {}}
    tot = Counter()
    for cid, reps in sorted(by_case.items()):
        gold = load(args.cases / cid / "gold.json")
        concl = [json.dumps(x.get("conclusion"), sort_keys=True, ensure_ascii=False) for x in reps]
        agree = Counter(concl).most_common(1)[0][1] if concl else 0
        verdict_agree = Counter(json.dumps(x.get("verdict"), sort_keys=True) for x in reps).most_common(1)[0][1] if reps else 0
        row = {
            "n_runs": len(reps), "expected_verdict": gold.get("expected_verdict"),
            "verdicts": [x.get("verdict") for x in reps],
            "verdict_match_runs": {l: sum(bool(x.get("verdict_match", {}).get(l)) for x in reps) for l in LAYERS},
            "rule_a_violations": [x.get("rule_a_violation_count", 0) for x in reps],
            "overclaim_candidates": [x.get("overclaim_candidates", 0) for x in reps],
            "omission_candidates": [x.get("omission_candidates", 0) for x in reps],
            "spurious_candidates": [x.get("spurious_candidates", 0) for x in reps],
            "recap_msg_links": [x.get("recap_msg_link_count", 0) for x in reps],
            "contrast_links": [x.get("contrast_link_count", 0) for x in reps],
            "possible_contributor": [x.get("possible_contributor", {}) for x in reps],
            "recap_cited": [len(x.get("recap_cited_as_factor", [])) for x in reps],
            "injected_cited": [len(x.get("injected_cited", [])) for x in reps],
            "skipped_llm": [x.get("skipped_llm") for x in reps],
            "verify_status": [x.get("verify_status") for x in reps],
            "same_conclusion_runs": agree, "same_verdict_runs": verdict_agree,
            "cost": round(sum(x.get("cost", 0.0) for x in reps), 2),
        }
        summary["cases"][cid] = row
        (args.out / "cases" / f"{cid}.json").write_text(
            json.dumps({"case_id": cid, "summary": row, "reports": reps}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tot["reports"] += len(reps)
        tot["rule_a_violations"] += sum(row["rule_a_violations"])
        tot["overclaim_candidates"] += sum(row["overclaim_candidates"])
        tot["omission_candidates"] += sum(row["omission_candidates"])
        tot["spurious_candidates"] += sum(row["spurious_candidates"])
        tot["recap_msg_links"] += sum(row["recap_msg_links"])
        tot["contrast_links"] += sum(row["contrast_links"])
        tot["verdict_match_move"] += row["verdict_match_runs"]["move"]
        tot["verdict_match_relative"] += row["verdict_match_runs"]["relative"]
        tot["cases_all_3_same_conclusion"] += int(agree == len(reps) and len(reps) >= 3)
        tot["recap_cited"] += sum(row["recap_cited"])
        tot["injected_cited"] += sum(row["injected_cited"])
        tot["skipped_llm"] += sum(bool(s) for s in row["skipped_llm"])
        tot["cost_x100"] += int(round(row["cost"] * 100))
    tot["cost"] = tot.pop("cost_x100") / 100
    summary["totals"] = dict(tot)
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'케이스':24} {'기대(move/rel)':34} {'3회 판정(move/rel)':60} 위반 과장 누락 밖link 시황msg 대조 시황kind 일치 비용")
    for cid, row in summary["cases"].items():
        ev = row["expected_verdict"]
        vs = " | ".join(f"{(v or {}).get('move')}/{(v or {}).get('relative')}" for v in row["verdicts"])
        print(f"{cid:24} {ev.get('move')}/{ev.get('relative'):20} {vs:60} {row['rule_a_violations']} {row['overclaim_candidates']} "
              f"{row['omission_candidates']} {row['spurious_candidates']} {row['recap_msg_links']} {row['contrast_links']} "
              f"{row['recap_cited']} {row['same_conclusion_runs']}/{row['n_runs']} ₩{row['cost']}")
    print("합계:", json.dumps(summary["totals"], ensure_ascii=False))
    if unmatched:
        print("케이스에 대응하지 못한 parsed:", unmatched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
