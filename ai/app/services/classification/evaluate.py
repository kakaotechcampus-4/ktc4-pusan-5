"""분류 결과(사건 추출·종목 판정)를 정답과 대조하고, 토큰·비용을 센다. 사람이 볼 검토표도 만든다.

정답은 eval_data/*/labels.csv 다(뉴스 발췌 비교 실험, eval_data/SUMMARY.md). 한 행 = 기사 하나,
`정답 문장` 은 그 종목이 움직인 원인 문장 번호("1,3"), 원인이 없으면 "-" 다.
번호는 지금 문장 분리 규칙(splitter v1)과 같다 — 31건 모두 문장 수가 일치함을 확인했다.

**이 정답은 사람이 매긴 것이 아니다.** 2026-09-25 실험 때 Claude 가 기사를 고르고 정답을 적었다
(그 세션 기록에서 확인). 사람이 검증하기 전까지 점수는 지난 실행과 비교하는 방향 표시로만 쓴다.
검토표(write_review)로 사람이 정답과 자동 채점을 함께 확인한다.

채점은 두 가지이고, 서로 다른 단계를 잰다. **둘을 합쳐 하나의 정확도로 쓰지 않는다.**

문장 재현율 (sentence_recall) — ① 추출만 잰다. 지난 실험의 "원인을 빠짐없이 담음 / 일부라도
담음" 과 같은 기준이다.
    원인 있는 기사   근거 사건(price_move 제외)의 근거·문맥 문장이 정답 문장을
                    전부 덮으면 all, 하나라도 덮으면 some, 아니면 none
    원인 없는 기사   근거 사건 중 표기가 그 종목 이름과 같은 것이 없으면 pass
                    (link 처럼 표기 전체로 맞춘다. "삼성전자서비스" 는 삼성전자가 아니다)
                    다른 회사·산업 사건이 있는 건 괜찮다 — 이 종목의 직접 근거만 없으면 된다
    정답은 종목 하나 기준이고 추출은 기사 전체 기준이다. 그래서 "어느 사건이든 정답 문장을
    덮었나" 로 느슨하게 본다. 엉뚱한 사건이 정답 문장을 덮어도 맞은 걸로 센다. 문장을 잘 찾고
    종목·사건 연결을 틀려도 all 이 나오므로, 이 점수만으로 모델·프롬프트를 고르지 않는다.

종목 연결 (stock_linked) — ①~④ 를 끝까지 잰다. 정답 문장 → 그 문장을 담은 사건 → 그 사건의
정답 종목 판정까지 맞아야 한다.
    원인 있는 기사   정답 종목 판정이 붙음(DIRECT·INDIRECT_CONTEXT)인 근거 사건만으로
                    정답 문장을 전부 덮으면 all, 하나라도 덮으면 some, 아니면 none
    원인 없는 기사   정답 종목을 DIRECT 로 판정한 근거 사건이 없으면 pass.
                    배경(INDIRECT_CONTEXT)으로 붙은 건 "원인을 지어냄" 이 아니라 괜찮다
    정답 종목이 기준 JSON 에 없으면 후보가 될 수 없어 잴 수 없다(None).

결과 파일(classify_*.json)에는 verdict(문장 재현율, 예전 결과 파일과 같은 키)와
verdict_linked(종목 연결)로 남는다.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from app.services.classification import splitter
from app.services.classification.basis import Basis, normalize_mention
from app.services.classification.events import Event
from app.services.classification.pipeline import ClassifiedEvent

# 근거 후보가 아닌 역할. 등락만 말하는 사건은 "왜" 가 아니라 "얼마나" 다
NON_EVIDENCE_ROLES = frozenset({"price_move"})
# 종목 연결 채점에서 "그 종목에 붙었다" 로 보는 판정
ATTACHED_LABELS = frozenset({"DIRECT", "INDIRECT_CONTEXT"})


@dataclass(frozen=True)
class Label:
    article_id: str
    kind: str  # 단일종목·여러종목·외국어·원인없음 …
    stock: str
    gold: frozenset[int]  # 비면 원인 없음
    memo: str
    reason: str = ""  # 정답을 적은 쪽이 쓴 원인 한 줄


def load_labels(path: Path) -> dict[str, Label]:
    labels = {}
    # 엑셀에서 저장해 BOM 이 붙어 있다
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw = row["정답 문장"].strip()
            gold = frozenset() if raw in ("", "-") else frozenset(int(n) for n in raw.split(","))
            labels[row["id"]] = Label(
                article_id=row["id"], kind=row["유형"], stock=row["종목"], gold=gold, memo=row["메모"],
                reason=row.get("이유(한 줄)", ""),
            )
    return labels


def evidence_events(events: list[Event]) -> list[Event]:
    return [e for e in events if e.role not in NON_EVIDENCE_ROLES]


def _coverage(events: list[Event], gold: frozenset[int]) -> str:
    covered = {i for e in events for i in (*e.sentence_indices, *e.context_indices)}
    if gold <= covered:
        return "all"
    return "some" if gold & covered else "none"


def sentence_recall(events: list[Event], label: Label) -> str:
    """① 추출만 본 문장 재현율. all / some / none (원인 있는 기사), pass / fail (원인 없는 기사)."""
    evidence = evidence_events(events)
    if not label.gold:
        about_stock = any(normalize_mention(label.stock) == normalize_mention(mention)
                          for e in evidence for mention in e.mentions)
        return "fail" if about_stock else "pass"
    return _coverage(evidence, label.gold)


def label_stock_code(label: Label, basis: Basis) -> str | None:
    """정답 종목 이름 → 기준 JSON 의 종목 코드. 이름·별칭을 표기 전체로 맞춘다."""
    target = normalize_mention(label.stock)
    for stock in basis.stocks.values():
        if target in {normalize_mention(n) for n in (stock.name, *stock.aliases)}:
            return stock.code
    return None


def stock_linked(events: list[ClassifiedEvent], label: Label, basis: Basis) -> str | None:
    """①~④ 끝까지 본 종목 연결. 값은 sentence_recall 과 같고, 기준 밖 종목이면 None."""
    code = label_stock_code(label, basis)
    if code is None:
        return None
    evidence = [item for item in events if item.event.role not in NON_EVIDENCE_ROLES]

    def labels_for(item: ClassifiedEvent) -> set[str]:
        return {j.label for j in item.judgments if j.stock_code == code}

    if not label.gold:
        return "fail" if any("DIRECT" in labels_for(item) for item in evidence) else "pass"
    attached = [item.event for item in evidence if labels_for(item) & ATTACHED_LABELS]
    return _coverage(attached, label.gold)


@dataclass(frozen=True)
class Tokens:
    prompt: int = 0
    completion: int = 0
    reasoning: int = 0  # completion 안에 포함된 추론 토큰. 프로바이더가 안 주면 0

    def __add__(self, other: "Tokens") -> "Tokens":
        return Tokens(self.prompt + other.prompt, self.completion + other.completion,
                      self.reasoning + other.reasoning)

    @property
    def total(self) -> int:
        return self.prompt + self.completion


def tokens_of(usage: dict) -> Tokens:
    details = usage.get("completion_tokens_details") or {}
    return Tokens(
        prompt=int(usage.get("prompt_tokens") or 0),
        completion=int(usage.get("completion_tokens") or 0),
        reasoning=int(details.get("reasoning_tokens") or 0),
    )


def tokens_line(tokens: Tokens) -> str:
    line = f"입력 {tokens.prompt:,} · 출력 {tokens.completion:,}"
    if tokens.reasoning:
        line += f"(추론 {tokens.reasoning:,})"
    return line + f" = {tokens.total:,} 토큰"


# 검토표 칸. "사람:" 칸은 비워 두고 사람이 채운다. 엑셀에서 바로 열리게 BOM 을 붙여 쓴다.
REVIEW_COLUMNS = [
    "id", "유형", "종목", "제목", "상태",
    "정답 이유", "정답 문장",
    "뽑힌 사건",
    "자동 채점: 문장 재현율",
    "자동 채점: 종목 연결",
    "사람: 정답이 맞나 (Y/N)",
    "사람: 추출 판정 (all/some/none/pass/fail)",
    "사람: 메모",
    "전체 문장",
]


def _numbered(sentences: list[str], indices) -> str:
    if not isinstance(indices, (list, tuple, range)):
        return ""
    return "\n".join(f"{i}. {sentences[i - 1]}" for i in indices
                     if type(i) is int and 1 <= i <= len(sentences))


def _event_block(event: dict, sentences: list[str]) -> str:
    """결과 파일의 사건 하나. 실패한 회차는 응답 원문의 키(sentences·context)를 그대로 쓴다.

    종목 판정이 있으면 끝에 "→ 종목 코드 판정" 으로 붙인다. 종목 연결 채점을 사람이 확인할 수 있게.
    """
    indices = event.get("sentence_indices", event.get("sentences")) or []
    context = event.get("context_indices", event.get("context")) or []
    head = (f"[{event.get('order_index', '?')}] {event.get('scope')} / {event.get('role')} / "
            f"{event.get('tense')}  표기 {event.get('mentions')}")
    lines = [head]
    lines += [f"  (문맥) {line}" for line in _numbered(sentences, context).splitlines()]
    lines += [f"  {line}" for line in _numbered(sentences, indices).splitlines()]
    judgments = event.get("judgments")
    if isinstance(judgments, list):
        lines += [f"  → {j.get('stock_code')} {j.get('label')}" for j in judgments
                  if isinstance(j, dict)]
    return "\n".join(lines)


def _csv_text(value: object) -> str:
    """기사 제목처럼 밖에서 온 글이 엑셀에서 수식으로 실행되지 않게 앞에 ' 를 붙인다."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def write_review(result: dict, articles: dict, out: Path,
                 labels: dict[str, Label] | None = None) -> int:
    """묶음 실행 결과(classify_*.json) → 검토표 CSV. 쓴 행 수를 돌려준다.

    정답 이유는 labels.csv 에서 읽는다. 예전 결과 파일에는 저장돼 있지 않다.
    """

    rows = []
    for item in result["results"]:
        article = articles.get(item["id"], {})
        run = item["run"]
        sentences = splitter.split(article.get("body") or "", run.get("splitter_version") or "v1")
        label = item.get("label") or {}
        gold = label.get("gold") or []

        events = run.get("events") or []
        status = run["status"]
        if status != "ok":
            status += f" — {run.get('error') or ''}"
            # 형식이 깨져 저장되지 않은 사건도 사람이 볼 수 있게 응답 원문에서 꺼낸다
            try:
                events = [dict(e, order_index=n) for n, e in
                          enumerate(json.loads(run.get("raw_response") or "")["events"], start=1)]
            except (ValueError, KeyError, TypeError):
                events = []

        rows.append({
            "id": item["id"],
            "유형": label.get("kind", ""),
            "종목": label.get("stock", ""),
            "제목": item.get("title") or "",
            "상태": status,
            "정답 이유": labels[item["id"]].reason if labels and item["id"] in labels
                         else label.get("reason", ""),
            "정답 문장": _numbered(sentences, gold) if gold else "(원인 없음)",
            "뽑힌 사건": "\n\n".join(_event_block(e, sentences) for e in events) or "(사건 없음)",
            "자동 채점: 문장 재현율": item.get("verdict") or "",
            # 예전 결과 파일에는 없다. 정답 종목이 기준 밖이어도 비어 있다
            "자동 채점: 종목 연결": item.get("verdict_linked") or "",
            "전체 문장": _numbered(sentences, range(1, len(sentences) + 1)),
        })

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows({key: _csv_text(value) for key, value in row.items()} for row in rows)
    return len(rows)
