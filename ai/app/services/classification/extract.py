"""기사 하나 → LLM 사건 추출 한 회차.

    본문 → 문장 번호(splitter) → LLM(prompts/classification_events.md) → 응답 검사(events)

결과(ExtractionRun)의 칸은 DRAFT 4-3 `classification_runs` 의 칼럼과 같게 맞췄다. 표가 생기면
그대로 옮겨 담는다. 지금은 DB 에 쓰지 않는다.

실패는 버리지 않고 상태로 남긴다(전제 P7).
    ok        사건 목록을 얻음. 빈 목록도 ok 다 — "이유가 될 내용이 없는 기사" 라는 판단이다
    failed    호출 실패, 응답 형식 깨짐. 응답 원문은 raw_response 에 남긴다
    no_body   본문이 없다. 요약 같은 다른 글로 대신 분류하지 않는다(DRAFT 4-3)
    skipped   분류하지 않기로 한 자료. 지금은 본문이 상한보다 긴 경우뿐이다

설정이 빠진 것(API 키 없음)은 자료 탓이 아니라서 상태로 남기지 않고 RuntimeError 로 멈춘다.
"""

import hashlib
from dataclasses import dataclass, field

from app.core.config import settings
from app.llm.client import LLMError, complete, load_prompt
from app.services.classification import splitter
from app.services.classification.events import Event, EventParseError, parse_events

PROMPT_NAME = "classification_events"
# Elice 는 스트리밍이 아닌 요청에서 2,000 을 넘으면 400 으로 거절한다(2026-10-21 확인:
# "max_tokens 4000 exceeds the 2000-token ceiling this proxy holds a NON-STREAMING reply to").
# 사건 하나가 JSON 으로 100~150 토큰쯤이라 사건 10개 남짓까지 든다. 추론 모델은 reasoning 도
# 이 한도에서 쓰므로, 잘리면 finish_reason=length 로 failed 가 난다 — 그때 reason 을 빼거나
# client 에 스트리밍을 붙이는 걸 검토한다.
MAX_TOKENS = 2000
# 이보다 긴 본문은 보내지 않는다. 뉴스는 대개 3,000자 안쪽이다. 증권사 PDF 처럼 긴 자료를
# 어떻게 나눠 보낼지는 아직 정하지 않았다 — 정하기 전까지 비용이 튀지 않게 막아 둔다.
MAX_INPUT_CHARS = 20_000


@dataclass
class ExtractionRun:
    status: str
    model: str | None = None
    prompt_sha256: str | None = None
    splitter_version: str | None = None
    input_sha256: str | None = None  # LLM 에 보낸 사용자 메시지의 해시
    sentence_count: int | None = None
    events: list[Event] = field(default_factory=list)
    dropped_mentions: list[tuple[int, str]] = field(default_factory=list)
    raw_response: str | None = None
    error: str | None = None
    usage: dict = field(default_factory=dict)


def build_user_message(title: str, sentences: list[str]) -> str:
    return f"[제목] {title.strip()}\n\n[본문]\n{splitter.numbered(sentences)}"


async def extract_events(body: str | None, title: str = "", *, model: str | None = None) -> ExtractionRun:
    if not body or not body.strip():
        return ExtractionRun(status="no_body")
    if len(body) > MAX_INPUT_CHARS:
        return ExtractionRun(
            status="skipped", error=f"본문 {len(body):,}자 — 상한 {MAX_INPUT_CHARS:,}자를 넘는다",
        )

    system = load_prompt(PROMPT_NAME)
    sentences = splitter.split(body, splitter.LATEST)
    user = build_user_message(title, sentences)
    run = ExtractionRun(
        status="failed",
        model=model or settings.summary_model,
        prompt_sha256=hashlib.sha256(system.encode("utf-8")).hexdigest(),
        splitter_version=splitter.LATEST,
        input_sha256=hashlib.sha256(user.encode("utf-8")).hexdigest(),
        sentence_count=len(sentences),
    )
    try:
        text, usage = await complete(system, user, model=model, max_tokens=MAX_TOKENS)
    except LLMError as exc:
        run.error = str(exc)
        return run
    run.raw_response, run.usage = text, usage

    try:
        parsed = parse_events(text, sentences, title)
    except EventParseError as exc:
        # 한도에 걸려 잘린 응답이면 JSON 이 깨진다. 원인을 알 수 있게 같이 남긴다
        finish = usage.get("finish_reason")
        run.error = f"{exc} (finish_reason={finish})" if finish not in (None, "stop") else str(exc)
        return run
    run.status = "ok"
    run.events = parsed.events
    run.dropped_mentions = parsed.dropped_mentions
    return run
