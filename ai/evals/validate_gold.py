"""gold.json 검증 스크립트. `rubric.md` 의 규칙을 기계적으로 확인한다. 표준 라이브러리만 쓴다.

    python3 evals/validate_gold.py                 # 전체 케이스
    python3 evals/validate_gold.py c07 c10         # 케이스 id 앞부분으로 골라서
    python3 evals/validate_gold.py --strict        # 아직 쓰지 않은(skeleton) 케이스도 오류로 본다
    python3 evals/validate_gold.py --root DIR      # 케이스 폴더 위치 지정(기본 evals/cases)

key_facts 는 표기 차이를 허용해 대조한다(공백·쉼표 무시, 금액 단위 환산, 낱말 부분 일치). 어느 근거에도 없으면 오류,
일부 토큰만 찾으면 경고(표기 차이인지 사람이 확인), 일부 근거에만 없으면 경고(그 source 인용 시 SOURCE_MISMATCH 후보)다.

ai/ 폴더에서 실행한다. 오류(✗)가 있으면 종료 코드 1, 경고(!)는 확인용이다.
의미 판단(원인인지, 방향이 맞는지)은 사람이 하고, 여기서는 규칙 위반과 근거 대조만 본다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, time
from pathlib import Path

IMPORTANCE = ("must", "should", "optional")
LAYERS = ("move", "relative")
STANCE = ("bullish", "bearish", "neutral")
MENTION = ("factors", "background", "either")
STRENGTH = ("coincident", "possible_contributor", "likely_cause")
STRENGTH_RANK = {s: i for i, s in enumerate(STRENGTH)}
VERDICT = ("explained", "partially_explained", "no_clear_cause")
CONFIDENCE = ("partial", "none")
TIER = ("primary", "secondary")
CLAIM_TYPE = ("false_cause", "direction_flip", "fabricated_cause", "result_as_cause", "market_direction", "advice")
RELATION_MIN = ("none", "coincident", "possible_contributor", "likely_cause")
DIRECTION = ("up", "down", None)
MARKET_CLOSE = time(15, 30)
# 복수 원인인 날(사건 2개 이상) 중요도별 상한(rubric §4-2)
IMPORTANCE_CEILING = {"must": "likely_cause", "should": "possible_contributor", "optional": "coincident"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)


def norm(text: str) -> str:
    """공백과 쉼표·콜론 같은 구두점을 빼고 소문자로. key_facts 대조는 이 꼴끼리 비교한다."""
    return re.sub(r"[\s,:;·•]+", "", text).lower()


UNIT = {"조": 1e12, "억": 1e8, "만": 1e4}
AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(조|억|만)")
PERCENT_RE = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*%")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _decimals(num_text: str) -> int:
    return len(num_text.split(".")[1]) if "." in num_text else 0


def parse_amounts(text: str) -> list[tuple[float, float]]:
    """금액(조·억·만)을 원 단위로 바꾼 (값, 허용 오차) 목록. "83조 3,338억원" 처럼 붙어 있는 단위는 합친다.
    허용 오차는 적힌 마지막 자리의 반올림 폭(83.3조 → 0.05조)."""
    found = [(m.start(), m.end(), m.group(1), m.group(2)) for m in AMOUNT_RE.finditer(text)]
    groups: list[list[tuple[int, int, str, str]]] = []
    for item in found:
        if groups and text[groups[-1][-1][1]:item[0]].strip() in ("", "원"):
            groups[-1].append(item)
        else:
            groups.append([item])
    out = []
    for g in groups:
        total = sum(float(n.replace(",", "")) * UNIT[u] for _, _, n, u in g)
        last_num, last_unit = g[-1][2], g[-1][3]
        out.append((total, 0.5 * 10 ** (-_decimals(last_num)) * UNIT[last_unit]))
    return out


def fact_match(fact: str, body_text: str) -> tuple[str, list[str]]:
    """key_fact 가 본문에 있는지. ("exact" | "fuzzy" | "partial" | "none", 못 찾은 토큰).

    exact   공백·쉼표·콜론을 뺀 글자가 그대로 들어 있음
    fuzzy   토큰마다 찾음. 금액은 단위를 환산해(83.3조원 = 83조 3,338억원) 반올림 오차 안에서, 퍼센트·숫자는 값으로,
            낱말은 부분 일치(컨센 = 컨센서스)로 본다
    partial 일부 토큰만 찾음
    none    하나도 못 찾음
    """
    if norm(fact) in norm(body_text):
        return "exact", []
    body_norm = norm(body_text)
    body_amounts = parse_amounts(body_text)
    body_pcts = [(abs(float(m.group(1).replace(",", ""))), 0.5 * 10 ** (-_decimals(m.group(1).lstrip("+-"))))
                 for m in PERCENT_RE.finditer(body_text)]
    body_plain = [float(m.group().replace(",", "")) for m in NUMBER_RE.finditer(AMOUNT_RE.sub(" ", PERCENT_RE.sub(" ", body_text)))]
    missing: list[str] = []
    n_tokens = 0
    for tok in fact.split():
        n_tokens += 1
        amounts = parse_amounts(tok)
        pcts = list(PERCENT_RE.finditer(tok))
        if amounts:
            ok = (any(abs(v - bv) <= max(tol, btol) + 1e-6 for v, tol in amounts for bv, btol in body_amounts)
                  or any(abs(v - bv) <= tol + 1e-6 for v, tol in amounts for bv in body_plain))  # 2만원 = 20,000원
        elif pcts:
            v = abs(float(pcts[0].group(1).replace(",", "")))
            tol = 0.5 * 10 ** (-_decimals(pcts[0].group(1).lstrip("+-")))
            ok = any(abs(v - bv) <= max(tol, btol) + 1e-6 for bv, btol in body_pcts)
        elif NUMBER_RE.fullmatch(re.sub(r"[원주배위개건명]+$", "", tok)):
            val = float(re.sub(r"[원주배위개건명]+$", "", tok).replace(",", ""))
            ok = val in body_plain or any(abs(val - bv) <= btol + 1e-6 for bv, btol in body_amounts)  # 20,000원 = 2만원
        else:
            w = norm(re.sub(r"^[^\w]+|[^\w]+$", "", tok))
            ok = bool(w) and (w in body_norm or (len(w) >= 3 and w[:-1] in body_norm))
        if not ok:
            missing.append(tok)
    if not missing:
        return "fuzzy", []
    return ("none" if len(missing) == n_tokens else "partial"), missing


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sign(x: float | None) -> int:
    if x is None or x == 0:
        return 0
    return 1 if x > 0 else -1


def layer_pct(me: dict, layer: str) -> float | None:
    return me.get("stock_change_pct") if layer == "move" else me.get("excess_vs_peers_pp")


def enum_check(r: Report, where: str, value, allowed, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if value not in allowed:
        r.err(f"{where}: `{value}` 는 허용 값이 아님 {list(allowed)}")


def check_skeleton_progress(r: Report, gold: dict) -> list[str]:
    """아직 비어 있는 칸 목록."""
    todo = []
    ev = gold.get("expected_verdict") or {}
    if ev.get("move") is None or ev.get("relative") is None:
        todo.append("expected_verdict")
    if gold.get("confidence_level") is None:
        todo.append("confidence_level")
    events = gold.get("events") or []
    if not events or all(not (e.get("summary") or "").strip() for e in events):
        todo.append("events")
    if not gold.get("forbidden_claims"):
        todo.append("forbidden_claims")
    if not gold.get("unknowns"):
        todo.append("unknowns")
    return todo


def check_case(case_dir: Path, strict: bool) -> Report:
    r = Report()
    gold = load(case_dir / "gold.json")
    case = load(case_dir / "case.json")
    prov = load(case_dir / "provenance.json")
    me = gold.get("market_expectation") or {}
    status = gold.get("status")
    skeleton = status == "skeleton"

    # ── 공통(뼈대 포함) ──────────────────────────────────────────────
    if gold.get("case_id") != case_dir.name:
        r.err(f"case_id `{gold.get('case_id')}` 가 폴더 이름과 다름")
    tx = gold.get("time_expectation") or {}
    if tx.get("cutoff") != case.get("cutoff"):
        r.err(f"time_expectation.cutoff `{tx.get('cutoff')}` 가 case.json cutoff `{case.get('cutoff')}` 와 다름")
    jl = me.get("judge_layers") or {}
    for key in ("judge_layers", "common_move", "market_led", "relative_direction", "excess_vs_peers_pp"):
        if me.get(key) is None:
            r.err(f"market_expectation.{key} 가 비어 있음(파이프라인 값으로 채워야 함)")
    if me.get("stock_change_pct") is not None and me["stock_change_pct"] != case.get("change_pct"):
        r.warn(f"stock_change_pct {me['stock_change_pct']} 와 case.json change_pct {case.get('change_pct')} 가 다름")

    todo = check_skeleton_progress(r, gold)
    if skeleton:
        if strict:
            r.err(f"아직 작성하지 않음(status: skeleton). 비어 있는 칸: {', '.join(todo) or '없음'}")
        else:
            r.info(f"작성 전(skeleton). 비어 있는 칸: {', '.join(todo) or '없음'}")
        return r

    # ── 작성된 gold 검증 ──────────────────────────────────────────────
    ev = gold.get("expected_verdict") or {}
    conf = gold.get("confidence_level")
    for layer in LAYERS:
        enum_check(r, f"expected_verdict.{layer}", ev.get(layer), VERDICT)
    enum_check(r, "confidence_level", conf, CONFIDENCE)

    # 판정 ↔ 확신 수준
    verdicts = [ev.get(l) for l in LAYERS]
    if conf == "none" and any(v != "no_clear_cause" for v in verdicts):
        r.err("confidence_level `none` 인데 `no_clear_cause` 가 아닌 층이 있음")
    if conf == "partial" and all(v == "no_clear_cause" for v in verdicts):
        r.err("confidence_level `partial` 인데 두 층 모두 `no_clear_cause`")

    # 판정 ↔ 시장 칸
    for layer in LAYERS:
        if jl.get(layer) is False and ev.get(layer) != "no_clear_cause":
            r.err(f"{layer} 층은 judge_layers false(|값| 1 이하)라 `no_clear_cause` 여야 함(현재 `{ev.get(layer)}`)")
    if me.get("common_move") is True and ev.get("move") != "no_clear_cause":
        r.err("common_move true 인 날은 move 판정이 `no_clear_cause` 여야 함")

    events = gold.get("events") or []
    ids = [e.get("id") for e in events]
    if len(ids) != len(set(ids)):
        r.err(f"사건 id 가 중복됨: {ids}")
    msgs = {m["url"]: m for m in case.get("messages", [])}
    injected = {x["url"] if isinstance(x, dict) else x for x in prov.get("injected_after_cutoff", [])}
    cutoff = datetime.fromisoformat(case["cutoff"])
    target = case["target_date"]
    must_n = sum(1 for e in events if e.get("importance") == "must")
    if must_n > 2:
        r.err(f"must 가 {must_n}개(최대 2개)")
    if conf == "none" and must_n > 0:
        r.err("confidence_level `none`(원인 없는 날)인데 must 사건이 있음")
    if not events:
        r.info("사건 없음(events: [])")

    for e in events:
        eid = e.get("id", "?")
        w = f"{eid}"
        if not (e.get("summary") or "").strip():
            r.err(f"{w}: summary 가 비어 있음")
        enum_check(r, f"{w}.importance", e.get("importance"), IMPORTANCE)
        enum_check(r, f"{w}.stance", e.get("stance"), STANCE)
        enum_check(r, f"{w}.expected_mention", e.get("expected_mention"), MENTION)
        enum_check(r, f"{w}.max_causal_strength", e.get("max_causal_strength"), STRENGTH)
        strength = e.get("max_causal_strength")
        layers = e.get("layer") or []
        for l in layers:
            enum_check(r, f"{w}.layer", l, LAYERS)
            if jl.get(l) is False:
                r.err(f"{w}: {l} 층은 판단하지 않는 층(judge_layers false)이라 사건을 달 수 없음")
            if l == "move" and me.get("common_move") is True:
                r.err(f"{w}: common_move true 인 날은 move 층에 사건을 달 수 없음")
            if l == "move" and me.get("move_strength_cap") == "partial" and strength == "likely_cause":
                r.err(f"{w}: move_strength_cap partial 인 날 move 층 사건은 likely_cause 를 쓸 수 없음")
            pct = layer_pct(me, l)
            st = e.get("stance")
            if (st in ("bullish", "bearish") and sign(pct) and (1 if st == "bullish" else -1) != sign(pct)
                    and strength in STRENGTH_RANK and strength != "coincident"):
                r.err(f"{w}: {l} 층 방향({pct:+})과 stance `{st}` 가 반대인데 상한이 `{strength}` (방향 반대 재료는 coincident)")
        if e.get("importance") == "must" and not layers:
            r.warn(f"{w}: must 인데 layer 가 비어 있음")
        # 복수 원인인 날 중요도별 상한
        if len(events) >= 2 and e.get("importance") in IMPORTANCE_CEILING and strength in STRENGTH_RANK:
            ceil = IMPORTANCE_CEILING[e["importance"]]
            if STRENGTH_RANK[strength] > STRENGTH_RANK[ceil]:
                r.err(f"{w}: 복수 원인인 날 {e['importance']} 의 상한은 `{ceil}` (현재 `{strength}`)")

        # 근거
        srcs = e.get("supporting_sources") or []
        if not srcs:
            r.err(f"{w}: supporting_sources 가 비어 있음")
        facts = [f for f in (e.get("key_facts") or []) if f.strip()]
        if srcs and not facts:
            r.err(f"{w}: key_facts 가 비어 있음")
        times: list[datetime] = []
        bodies: list[tuple[str, str]] = []
        for s in srcs:
            url = s.get("url") if isinstance(s, dict) else s
            enum_check(r, f"{w}.supporting_sources.tier", s.get("tier") if isinstance(s, dict) else None, TIER)
            if url in injected:
                r.err(f"{w}: {url} 는 cutoff 이후 삽입 자료(injected_after_cutoff)라 근거로 쓸 수 없음")
                continue
            m = msgs.get(url)
            if m is None:
                r.err(f"{w}: {url} 가 case.json 에 없음(입력 밖 source)")
                continue
            t = datetime.fromisoformat(m["datetime_kst"])
            times.append(t)
            if t > cutoff:
                r.err(f"{w}: {url} 시각 {t.isoformat()} 이 cutoff 이후")
            bodies.append((url, m["text"]))
        # key_facts 는 표기 차이를 허용해 대조한다. 어느 근거에도 없으면 오류, 일부 근거에만 없으면 경고
        for f in facts:
            results = [(u, *fact_match(f, t)) for u, t in bodies]
            if bodies and all(res in ("none", "partial") for _, res, _ in results):
                best = [x for x in results if x[1] == "partial"]
                if best:
                    r.warn(f"{w}: key_facts `{f}` 를 일부만 찾음(못 찾은 토큰 {best[0][2]}). 표기만 다른지 확인")
                else:
                    r.err(f"{w}: key_facts `{f}` 가 근거 본문 어디에도 없음")
            else:
                for u, res, miss in results:
                    if res in ("none", "partial"):
                        r.warn(f"{w}: key_facts `{f}` 가 {u} 에는 없음. 이 source 를 인용하면 SOURCE_MISMATCH 후보")
        if times:
            first = min(times)
            r.info(f"{w}: 가장 이른 근거 {first.strftime('%m-%d %H:%M')}")
            if first.date().isoformat() == target and first.time() > MARKET_CLOSE and strength in STRENGTH_RANK and strength != "coincident":
                r.err(f"{w}: 근거가 대상일 장 마감({MARKET_CLOSE:%H:%M}) 이후({first:%H:%M})에 공개됐는데 상한이 `{strength}` (coincident 이하여야 함)")

    # explained 판정은 방향이 맞는 사건이 있어야 함
    for layer in LAYERS:
        if ev.get(layer) == "explained":
            pct = layer_pct(me, layer)
            ok = [e for e in events if layer in (e.get("layer") or [])
                  and e.get("stance") in ("bullish", "bearish")
                  and (1 if e["stance"] == "bullish" else -1) == sign(pct)
                  and e.get("max_causal_strength") == "likely_cause"]
            if not ok:
                r.err(f"{layer} 가 `explained` 인데 방향이 맞고 likely_cause 인 사건이 없음")
        if ev.get(layer) in ("explained", "partially_explained") and not any(layer in (e.get("layer") or []) for e in events):
            r.warn(f"{layer} 가 `{ev.get(layer)}` 인데 그 층에 달린 사건이 없음")
        if ev.get(layer) == "no_clear_cause" and any(layer in (e.get("layer") or []) and e.get("importance") == "must" for e in events):
            r.warn(f"{layer} 가 `no_clear_cause` 인데 그 층에 must 사건이 있음")

    # 금지 주장
    fids = []
    all_text = norm(" ".join(m["text"] for m in case.get("messages", [])))
    for c in gold.get("forbidden_claims") or []:
        cid = c.get("id", "?")
        fids.append(cid)
        enum_check(r, f"{cid}.type", c.get("type"), CLAIM_TYPE)
        enum_check(r, f"{cid}.relation_min", c.get("relation_min"), RELATION_MIN)
        if c.get("direction") not in DIRECTION:
            r.err(f"{cid}.direction: `{c.get('direction')}` 는 허용 값이 아님 (up/down/null)")
        if not (c.get("subject") or "").strip():
            r.err(f"{cid}: subject 가 비어 있음")
        if not (c.get("example") or "").strip():
            r.warn(f"{cid}: example 이 없음(사람이 읽는 예시)")
        if c.get("type") == "fabricated_cause" and c.get("subject") and norm(c["subject"]) in all_text:
            r.warn(f"{cid}: subject `{c['subject']}` 가 입력 메시지에 나옴. 입력에 근거가 있으면 금지 주장이 아님")
    if len(fids) != len(set(fids)):
        r.err(f"금지 주장 id 가 중복됨: {fids}")
    if len(fids) > 3:
        r.warn(f"forbidden_claims 가 {len(fids)}개(권장 2~3개)")
    if not gold.get("unknowns"):
        r.warn("unknowns 가 비어 있음")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="gold.json 검증")
    ap.add_argument("cases", nargs="*", help="케이스 id 앞부분(예: c07). 비우면 전체")
    ap.add_argument("--root", default=str(Path(__file__).parent / "cases"))
    ap.add_argument("--strict", action="store_true", help="skeleton 케이스도 오류로 처리")
    args = ap.parse_args()

    root = Path(args.root)
    dirs = sorted(d for d in root.iterdir() if d.is_dir() and (d / "gold.json").exists())
    if args.cases:
        dirs = [d for d in dirs if any(d.name.startswith(p) for p in args.cases)]
    if not dirs:
        print("검증할 케이스가 없음")
        return 1

    total_err = 0
    rows = []
    for d in dirs:
        rep = check_case(d, args.strict)
        total_err += len(rep.errors)
        print(f"\n== {d.name}")
        for m in rep.errors:
            print(f"  ✗ {m}")
        for m in rep.warnings:
            print(f"  ! {m}")
        for m in rep.infos:
            print(f"  · {m}")
        if not (rep.errors or rep.warnings or rep.infos):
            print("  ✓ 이상 없음")
        rows.append((d.name, len(rep.errors), len(rep.warnings)))

    print("\n" + "-" * 50)
    print(f"{'케이스':<28}{'오류':>5}{'경고':>5}")
    for name, e, w in rows:
        print(f"{name:<28}{e:>5}{w:>5}")
    print(f"합계: 오류 {total_err}건")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
