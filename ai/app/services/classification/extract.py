"""① 사건 추출 — 자료 하나를 LLM 에 한 번 보내 사건 목록을 받는다(전제 P2·P3).

    본문 → 문장 번호(splitter) → LLM(prompts/classification_events.md) → 응답 검사(events)

LLM 은 근거를 문장 번호로만 낸다. 문장을 옮겨 쓰지 않으므로 근거를 지어낼 수 없다.
사건은 넓게 남긴다. 어느 종목에 붙일지는 뒤 단계(②~④)가 정한다.
"""

from dataclasses import dataclass, field

from app.services.classification import llm, splitter
from app.services.classification.events import Event, EventParseError, parse_events

PROMPT_NAME = "classification_events"
# 제목·본문을 합쳐 이보다 길면 보내지 않는다(회차 status = skipped). 뉴스는 대개 3,000자 안쪽이다.
# 증권사 PDF 처럼 긴 자료를 어떻게 나눠 보낼지는 아직 정하지 않았다 — 정하기 전까지 비용이 튀지 않게 막는다.
MAX_INPUT_CHARS = 20_000


@dataclass
class Extraction:
    call: llm.StepCall
    events: list[Event] = field(default_factory=list)
    dropped_mentions: list[tuple[int, str]] = field(default_factory=list)  # 원문에 없어 뺀 (사건, 표기)
    error: str | None = None


def build_user_message(title: str, sentences: list[str]) -> str:
    return f"[제목] {title.strip()}\n\n[본문]\n{splitter.numbered(sentences)}"


async def extract_events(title: str, sentences: list[str], *, model: str | None = None) -> Extraction:
    call = await llm.call("extract", PROMPT_NAME, build_user_message(title, sentences), model=model)
    result = Extraction(call=call)
    if not call.ok:
        result.error = call.error
        return result
    try:
        parsed = parse_events(call.raw_response or "", sentences, title)
    except EventParseError as exc:
        result.error = llm.parse_failure(call, str(exc))
        return result
    result.events, result.dropped_mentions = parsed.events, parsed.dropped_mentions
    return result
