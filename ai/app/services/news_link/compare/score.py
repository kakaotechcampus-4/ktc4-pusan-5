"""채점. 네트워크·LLM 을 쓰지 않는 순수 함수만 둔다 — 테스트할 수 있어야 해서다.

A·B 는 정답 문장 번호와 비교해 자동으로 채점한다. C 와 "B 가 혼자 읽혀도 뜻이
통하는가" 는 사람이 review.csv 에 적은 값을 모은다.
"""

import re
from collections import defaultdict

# 사람이 엑셀에서 적는 값이라 표기가 흔들린다. 흔한 것은 다 받는다.
_YES = {"y", "yes", "o", "예", "네", "1", "true", "ㅇ"}
_NO = {"n", "no", "x", "아니오", "아니요", "0", "false", "ㄴ"}
_NONE_ANSWER = {"-", "없음", "none", "x"}
_RANGE_RE = re.compile(r"^(\d+)\s*[-~]\s*(\d+)$")


def parse_answer(cell: str | None) -> set[int] | None:
    """정답 칸. '6,7,8' '6-8' '6, 8' → {6, 7, 8}. '-' '없음' → 빈 집합. 빈칸 → None.

    빈 집합과 None 을 가르는 이유: 빈 집합은 "이 기사에 이 종목의 원인이 없다" 는
    **정답**이고, None 은 아직 안 적었다는 뜻이다. 둘을 섞으면 안 적은 칸이
    "원인 없음" 으로 채점된다.
    """
    text = (cell or "").strip()
    if not text:
        return None
    if text.lower() in _NONE_ANSWER:
        return set()
    out: set[int] = set()
    for part in re.split(r"[,\s/]+", text):
        if not part:
            continue
        if part.isdigit():
            out.add(int(part))
            continue
        span = _RANGE_RE.match(part)
        if span and int(span.group(1)) <= int(span.group(2)):
            out.update(range(int(span.group(1)), int(span.group(2)) + 1))
            continue
        raise ValueError(f"정답 칸을 읽을 수 없다: {cell!r} (예: 6,7,8 / 6-8 / -)")
    return out


def parse_mark(cell: str | None) -> bool | None:
    """review.csv 의 예/아니오 칸. 빈칸·알 수 없는 값은 None(채점 안 함)."""
    text = (cell or "").strip().lower()
    if text in _YES:
        return True
    if text in _NO:
        return False
    return None


def compare(answer: set[int], selected: list[int]) -> dict:
    """정답 번호와 고른 번호 비교.

    all_in   정답 문장을 **전부** 담았나. 원인 설명에 필요한 문장이 다 들어갔다는 뜻이라
             가장 엄한 기준이고, 방식을 고를 때 이걸 먼저 본다
    any_in   정답 문장을 하나라도 담았나. 원인의 실마리라도 들어갔는가
    recall   정답 중 담은 비율
    precision 고른 것 중 정답 비율. 낮으면 쓸데없는 문장이 payload 를 먹는다

    정답이 빈 집합("원인 없음")이면 위 지표를 셀 수 없다. 그때는 "아무것도 안 골랐나" 만 본다.
    """
    chosen = set(selected)
    if not answer:
        return {"none_case": True, "none_correct": not chosen}
    hit = answer & chosen
    return {
        "none_case": False,
        "all_in": answer <= chosen,
        "any_in": bool(hit),
        "recall": len(hit) / len(answer),
        "precision": len(hit) / len(chosen) if chosen else 0.0,
    }


def _pct(num: int, den: int) -> str:
    return f"{num}/{den} ({num / den:.0%})" if den else "-"


def _avg(values: list[float], fmt: str = "{:.0%}") -> str:
    return fmt.format(sum(values) / len(values)) if values else "-"


def _selection_stats(rows: list[dict], key: str) -> dict:
    scored = [compare(r["answer"], r[key]) for r in rows]
    normal = [s for s in scored if not s["none_case"]]
    none_cases = [s for s in scored if s["none_case"]]
    return {
        "n": len(normal),
        "all_in": sum(s["all_in"] for s in normal),
        "any_in": sum(s["any_in"] for s in normal),
        "recall": [s["recall"] for s in normal],
        "precision": [s["precision"] for s in normal],
        "none_n": len(none_cases),
        "none_correct": sum(s["none_correct"] for s in none_cases),
    }


def _marks(rows: list[dict], method: str, field: str) -> tuple[int, int]:
    values = [r["review"].get((method, field)) for r in rows]
    values = [v for v in values if v is not None]
    return sum(values), len(values)


def render_report(rows: list[dict], skipped: list[dict]) -> str:
    """report.md 본문.

    rows 한 줄 = (기사, 종목) 한 쌍. 필요한 키:
        id kind stock answer(set)  a b(list[int])  b_fallback
        a_chars b_chars c_chars  c_unsupported(list)  b_cost c_cost
        review {(method, field): bool}   field 는 reason / invented / sense
    """
    a = _selection_stats(rows, "a")
    b = _selection_stats(rows, "b")
    c_reason = _marks(rows, "C", "reason")
    c_invented = _marks(rows, "C", "invented")
    b_sense = _marks(rows, "B", "sense")
    c_sense = _marks(rows, "C", "sense")
    c_numbers = sum(1 for r in rows if r["c_unsupported"])

    def chars(key: str) -> str:
        return _avg([r[key] for r in rows], "{:.0f}자")

    # (지표, A, B, C)
    table = [
        ("정답 문장 **전부** 포함", _pct(a["all_in"], a["n"]), _pct(b["all_in"], b["n"]),
         f"사람: 이유 포함 {_pct(*c_reason)}"),
        ("정답 문장 하나라도 포함", _pct(a["any_in"], a["n"]), _pct(b["any_in"], b["n"]), "-"),
        ("평균 재현율", _avg(a["recall"]), _avg(b["recall"]), "-"),
        ("평균 정밀도 (군더더기 적음)", _avg(a["precision"]), _avg(b["precision"]), "-"),
        ("'원인 없음' 기사를 비워둠", "불가 (항상 3문장)",
         _pct(b["none_correct"], b["none_n"]), "사람 채점"),
        ("원문에 없는 내용", "없음 (구조상)", "없음 (구조상)",
         f"사람: {_pct(*c_invented)} · 숫자 자동검사 {c_numbers}건"),
        ("혼자 읽어도 뜻이 통함", "- (연속 문장)", f"사람: {_pct(*b_sense)}",
         f"사람: {_pct(*c_sense)}"),
        ("규칙 위반 → A 로 대체", "-", f"{sum(r['b_fallback'] for r in rows)}건", "-"),
        ("평균 글자 수", chars("a_chars"), chars("b_chars"), chars("c_chars")),
        ("비용 합계", "$0", f"${sum(r['b_cost'] for r in rows):.4f}",
         f"${sum(r['c_cost'] for r in rows):.4f}"),
    ]
    lines = [
        "# 뉴스 발췌 방식 비교 결과",
        "",
        f"채점 대상 {len(rows)}쌍 · 본문을 못 읽어 뺀 것 {len(skipped)}쌍",
        "",
        "| 지표 | A 앞 3문장 | B 번호 선택 | C 생성 요약 |",
        "|---|---|---|---|",
        *(f"| {' | '.join(cells)} |" for cells in table),
        "",
        "C 의 '원문에 없는 내용' 은 **있었던 건수**다. 낮을수록 좋다.",
        "",
        "## 유형별 — 정답 문장 전부 포함",
        "",
        "| 유형 | A | B |",
        "|---|---|---|",
    ]
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_kind[row["kind"] or "(미지정)"].append(row)
    for kind, group in sorted(by_kind.items()):
        ka, kb = _selection_stats(group, "a"), _selection_stats(group, "b")
        lines.append(f"| {kind} | {_pct(ka['all_in'], ka['n'])} | {_pct(kb['all_in'], kb['n'])} |")

    # 숫자만 보면 "왜 졌는지" 를 모른다. 갈린 사례를 직접 열어봐야 다음 수정이 보인다.
    a_only, b_only = [], []
    for row in rows:
        if not row["answer"]:
            continue
        sa, sb = compare(row["answer"], row["a"]), compare(row["answer"], row["b"])
        if sa["all_in"] and not sb["all_in"]:
            a_only.append(row)
        elif sb["all_in"] and not sa["all_in"]:
            b_only.append(row)
    lines += ["", "## 갈린 사례", ""]
    lines.append("B 만 맞힘: " + (", ".join(f"{r['id']}({r['stock']})" for r in b_only) or "없음"))
    lines.append("")
    lines.append("A 만 맞힘: " + (", ".join(f"{r['id']}({r['stock']})" for r in a_only) or "없음"))
    numbers = [r for r in rows if r["c_unsupported"]]
    if numbers:
        lines += ["", "C 에서 본문에 없는 숫자:", ""]
        lines += [f"- {r['id']}({r['stock']}): {', '.join(r['c_unsupported'])}" for r in numbers]
    if skipped:
        lines += ["", "## 본문을 못 읽어 뺀 것", ""]
        lines += [f"- {s['id']} {s['domain'] or s['url']} — {s['status']}" for s in skipped]
    return "\n".join(lines) + "\n"
