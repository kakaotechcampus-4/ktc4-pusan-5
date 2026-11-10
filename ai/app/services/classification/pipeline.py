"""자료 하나 분류 — ①~④ 를 잇는다. DB 를 쓰지 않는다.

    ① 사건 추출(LLM) → ② 표기 → 종목·산업·외부 기업(사전, 안 잡히면 LLM 코드 선택)
    → ③ 후보 모으기(기준. 켜면 홍보성 사건을 Jev 에도 묻는다) → ④ 해당 여부 판정(LLM) + 저장 전 보정

결과(ClassificationResult)의 칸은 classification_runs 이하 표의 칼럼과 맞췄다. 저장은
repositories/classification.py 의 save_run 이 한다. 같은 함수를 DB 없이 실험 기사 묶음에도 쓴다
(`python -m app.services.classification eval`) — 모델을 바꿔 가며 비교할 때 DB 를 더럽히지 않는다.

상태 (전제 P7, 4-3)
    ok        사건 목록을 얻고 판정까지 마침. 사건이 없어도 ok 다 — "이유가 될 내용이 없는 자료"
    failed    ①·②·④ 중 하나라도 호출 실패나 응답 형식 깨짐. 응답 원문은 남긴다
              ③ Jev 실패는 회차를 실패로 만들지 않는다. 정규식만 본 결과로 이어 가고 usage 에 남긴다
    no_body   본문이 없다. 요약 같은 다른 글로 대신 분류하지 않는다
    skipped   제목·본문이 상한(MAX_INPUT_CHARS)보다 길다
"""

import hashlib
from dataclasses import dataclass, field

from app.services.classification import promo, splitter
from app.services.classification.basis import Basis
from app.services.classification.candidates import Candidate, collect_candidates
from app.services.classification.events import Event
from app.services.classification.extract import MAX_INPUT_CHARS, extract_events
from app.services.classification.judge import FIX_KEYS, Judgment, judge
from app.services.classification.link import (
    TARGET_SCOPES,
    EntityLink,
    Unresolved,
    alias_index,
    link_mentions,
    link_with_llm,
)
from app.services.classification.llm import StepCall

# 분류 기준(사건 형식·라벨 정의) 버전. 프롬프트의 값 목록(scope·role·tense·판정 라벨)을 바꾸면 올린다
CRITERIA_VERSION = "2026-10-30"


@dataclass
class ClassifiedEvent:
    event: Event
    links: list[EntityLink] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # 어디에도 안 이어진 표기 (막은 표기 포함)
    candidates: list[Candidate] = field(default_factory=list)
    judgments: list[Judgment] = field(default_factory=list)
    promo_jev: float | None = None  # Jev 홍보성 확률. 물어본 사건만(promo.py)


@dataclass
class ClassificationResult:
    status: str
    basis_version: str
    criteria_version: str = CRITERIA_VERSION
    splitter_version: str | None = None
    input_sha256: str | None = None  # 분류에 넣은 본문(body)의 해시. 원문이 그때와 같은지 맞춰 본다
    sentence_count: int | None = None
    events: list[ClassifiedEvent] = field(default_factory=list)
    dropped_mentions: list[tuple[int, str]] = field(default_factory=list)
    calls: dict[str, StepCall] = field(default_factory=dict)  # 부른 단계만
    judge_fixes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIX_KEYS, 0))
    error: str | None = None

    @property
    def usage(self) -> dict:
        """단계별 사용량. 단계마다 모델이 다를 수 있어 모델도 함께 남긴다."""
        return {step: call.usage_record() for step, call in self.calls.items()}

    @property
    def cost(self) -> float:
        return sum(record["cost"] for record in self.usage.values())

    @property
    def rate_limit_retries(self) -> int:
        return sum(call.rate_limit_retries for call in self.calls.values())

    def direct_stocks(self) -> set[str]:
        return {j.stock_code for e in self.events for j in e.judgments if j.label == "DIRECT"}


async def classify(title: str | None, body: str | None, basis: Basis, *,
                   models: dict[str, str | None] | None = None) -> ClassificationResult:
    models = models or {}
    title = title or ""
    if not body or not body.strip():
        return ClassificationResult(status="no_body", basis_version=basis.version)
    size = len(title) + len(body)
    if size > MAX_INPUT_CHARS:
        return ClassificationResult(
            status="skipped", basis_version=basis.version,
            error=f"제목·본문 {size:,}자 — 상한 {MAX_INPUT_CHARS:,}자를 넘는다",
        )

    sentences = splitter.split(body, splitter.LATEST)
    result = ClassificationResult(
        status="failed", basis_version=basis.version, splitter_version=splitter.LATEST,
        input_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        sentence_count=len(sentences),
    )

    # ① 사건 추출
    extraction = await extract_events(title, sentences, model=models.get("extract"))
    result.calls["extract"] = extraction.call
    if extraction.error:
        result.error = extraction.error
        return result
    result.dropped_mentions = extraction.dropped_mentions

    # ② 표기 연결: 사전 → 안 잡힌 표기만 LLM
    index = alias_index(basis)
    classified: list[ClassifiedEvent] = []
    asks: list[Unresolved] = []
    for event in extraction.events:
        linked = link_mentions(event.mentions, basis, index)
        item = ClassifiedEvent(event=event, links=linked.links,
                               unresolved=[*linked.unresolved, *linked.blocked])
        classified.append(item)
        if event.scope in TARGET_SCOPES:
            asks += [Unresolved(event.order_index, mention) for mention in linked.unresolved]
    by_order = {item.event.order_index: item for item in classified}
    coding = await link_with_llm(asks, {o: i.event for o, i in by_order.items()}, sentences, basis,
                                 model=models.get("link"))
    if coding.call is not None:
        result.calls["link"] = coding.call
    if coding.error:
        result.error = coding.error
        return result
    for order, links in coding.links.items():
        item = by_order[order]
        item.links += links
        item.unresolved = [m for m in item.unresolved if m not in {link.mention for link in links}]

    # ③ 후보. 근거 문장은 홍보성 사건을 관계로 넘기지 않을 때 본다(정규식)
    texts: dict[int, str] = {}
    for item in classified:
        texts[item.event.order_index] = " ".join(
            sentences[i - 1] for i in item.event.sentence_indices if 1 <= i <= len(sentences))
        item.candidates = collect_candidates(item.event, item.links, basis,
                                             texts[item.event.order_index])

    # ③ 홍보성 Jev (켰을 때만). 정규식에 안 걸려 관계 후보가 남은 사건만 묻는다. 실패하면 정규식 결과 그대로
    asks = [item for item in classified if any(c.relation_refs for c in item.candidates)]
    if promo.enabled() and asks:
        asked = await promo.check(title, sentences, [item.event for item in asks])
        result.calls[promo.STEP] = asked
        for item in asks:
            item.promo_jev = asked.probabilities.get(item.event.order_index)
            if promo.is_promo(item.promo_jev):
                item.candidates = collect_candidates(item.event, item.links, basis,
                                                     texts[item.event.order_index], promo=True)

    # ④ 판정
    judging = await judge(title, sentences, [(i.event, i.links, i.candidates) for i in classified],
                          basis, model=models.get("judge"))
    if judging.call is not None:
        result.calls["judge"] = judging.call
    if judging.relation_call is not None:  # 관계 후보를 Jev 로 판정했을 때(judge_relation.py)
        result.calls["judge_relation"] = judging.relation_call
    if judging.error:
        result.error = judging.error
        return result
    for (order, _), judgment in judging.judgments.items():
        by_order[order].judgments.append(judgment)
    for item in classified:
        order = [c.stock_code for c in item.candidates]
        item.judgments.sort(key=lambda j: order.index(j.stock_code))

    result.events = classified
    result.judge_fixes = judging.fixes
    result.status = "ok"
    return result
