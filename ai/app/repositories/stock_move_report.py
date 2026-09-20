"""보고서 JSON 을 읽어 DB 에 넣는다. 파싱 → 정규화 → (받아온 판정과 함께) INSERT.

입력은 `runs/<타임스탬프>/parsed/*.json` **파일**이다. 입력 테이블을 따로 두지 않는다 —
보고서 생성 결과는 매 실행마다 새로 만들어지는 일회성 산출물이라 원본을 DB 에 쌓을
이유가 없다. 수집 원본(analyst_reports, news)이 DB 에 있는 것과는 성격이 다르다.
파일은 사람이 runs/ 에서 가져다 둔다. 파이프라인 직결은 후속 PR 이다.

**파일은 2단이다.** 바깥은 실험 파이프라인의 실행 기록 래퍼고, 보고서 JSON 은
`final_text` 안에 **문자열로** 들어 있다. 래퍼를 열고 → final_text 를 다시 파싱한다.

래퍼에서 읽는 것은 다섯 개뿐이다. 나머지는 흘려보낸다 — 래퍼는 실험 환경 산출물이라
필드가 늘거나 줄고, 모르는 필드에 걸려 죽으면 적재가 통째로 멈춘다.

    final_text       보고서 JSON. 적재 대상
    json_status      파싱 성공 여부
    schema_problems  스키마 위반 목록
    is_error         실행 실패
    asked_question   되묻기 위반

툴 지표(n_tool_calls·tool_sequence·queries 등)는 툴을 막아둬서 언제나 0 이고,
pubdate_* 는 당일 생성으로 바뀌면서 의미가 없어졌다. **실패 판정에 쓰지 않는다.**
래퍼의 verdict / n_factors / n_sources 도 읽지 않는다. final_text 안의 값을 다시 센
것이라 두 군데 두면 어긋났을 때 무엇을 믿을지 문제가 된다. 단일 출처는 final_text 다.

**이 모듈은 근거 검증을 하지 않는다.** 판정은 인자로 받는다(`verify_status`).
검증기는 실험 레포에 있고 연결은 후속 PR 이다.
"""

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_move_report import (
    StockMoveReport,
    StockMoveReportFactor,
    StockMoveReportFactorSource,
)

logger = logging.getLogger(__name__)

# 프롬프트의 as_of 는 "HH:MM" 뿐이라 날짜와 합칠 때 타임존을 우리가 붙여야 한다.
# 대상이 한국 증시 장중 시각이므로 KST 고정이다. 루트 CLAUDE.md 가 naive datetime 을 금지한다.
KST = timezone(timedelta(hours=9))

# 시스템 프롬프트가 정한 상한. **초과해도 잘라내지 않는다.**
# 상한 위반 탐지는 실행 점검 스크립트 담당이고, 적재가 말없이 자르면 그 검사가
# 영원히 통과한다. 여기서는 그대로 넣고 로그에만 남긴다.
MAX_FACTORS = 4
MAX_TERMS = 8
MAX_BACKGROUND_TOTAL = 6
MAX_BACKGROUND_PER_SLOT = 3

BACKGROUND_SLOTS = ("bullish", "bearish", "neutral")


class ParsedReport:
    """파일 하나를 편 결과. DB 에 넣기 직전 형태다.

    파싱이 깨진 건도 여기까지는 온다 — 버리지 않고 상태만 달아 적재하기 때문이다.
    그때 `report` 는 비고 `raw_json` 에 래퍼가 통째로 들어 있다.
    """

    def __init__(
        self,
        *,
        run_id: str | None,
        report: dict[str, Any],
        raw_json: dict[str, Any],
        parse_status: str,
        parse_error: str | None,
    ) -> None:
        self.run_id = run_id
        self.report = report
        self.raw_json = raw_json
        self.parse_status = parse_status  # ok | schema_violation | parse_failed
        self.parse_error = parse_error


def _failed(run_id: str | None, raw_json: dict[str, Any], reason: str) -> ParsedReport:
    """파싱이 깨진 건. **버리지 않는다** — 원인 분석 자료가 사라진다."""
    return ParsedReport(
        run_id=run_id, report={}, raw_json=raw_json, parse_status="parse_failed", parse_error=reason
    )


def parse_report_file(path: Path) -> ParsedReport:
    """래퍼 파일 하나를 연다. 어떤 입력이 와도 예외를 던지지 않는다.

    적재가 멈추면 안 되는 자리다. 파일이 JSON 이 아니든 final_text 가 없든
    상태만 달아 넘기고, 원본은 raw_json 에 남긴다.
    """
    text = path.read_text(encoding="utf-8")
    try:
        wrapper = json.loads(text)
    except json.JSONDecodeError as e:
        # 파일 자체가 JSON 이 아니면 JSONB 에 넣을 객체가 없다. 원문을 감싸서라도 남긴다.
        return _failed(path.stem, {"_unparsed_text": text}, f"래퍼 JSON 파싱 실패: {e}")
    if not isinstance(wrapper, dict):
        return _failed(
            path.stem, {"_unparsed_text": text}, f"래퍼가 객체가 아니다: {type(wrapper).__name__}"
        )
    return parse_wrapper(wrapper, fallback_run_id=path.stem)


def parse_wrapper(wrapper: dict[str, Any], *, fallback_run_id: str | None = None) -> ParsedReport:
    """실행 기록 래퍼에서 보고서 JSON 을 꺼낸다. 다섯 필드만 본다."""
    run_id = wrapper.get("run_id") or fallback_run_id

    final_text = wrapper.get("final_text")
    if not isinstance(final_text, str) or not final_text.strip():
        return _failed(run_id, wrapper, "final_text 가 없거나 비어 있다")

    try:
        report = json.loads(final_text)
    except json.JSONDecodeError as e:
        return _failed(run_id, wrapper, f"final_text JSON 파싱 실패: {e}")
    if not isinstance(report, dict):
        return _failed(run_id, wrapper, f"보고서가 객체가 아니다: {type(report).__name__}")

    # 파싱은 됐지만 그대로 믿으면 안 되는 회차들. 셋은 원인이 다르지만 "이 산출물을
    # 서비스에 내보내면 안 된다" 는 뜻은 같아서 한 상태로 묶는다. 무엇이 걸렸는지는
    # parse_error 가 줄 단위로 말한다.
    problems: list[str] = []
    json_status = wrapper.get("json_status")
    if json_status is not None and json_status != "clean":
        problems.append(f"json_status={json_status}")
    schema_problems = wrapper.get("schema_problems")
    if isinstance(schema_problems, list) and schema_problems:
        problems.append(f"schema_problems={schema_problems}")
    if wrapper.get("is_error"):
        problems.append("is_error=true (실행 실패)")
    if wrapper.get("asked_question"):
        problems.append("asked_question=true (되묻기 금지 위반)")

    return ParsedReport(
        run_id=run_id,
        report=report,
        raw_json=report,  # 파싱 성공이면 raw_json 은 보고서 쪽이다. 래퍼는 운영 지표라 안 남긴다
        parse_status="schema_violation" if problems else "ok",
        parse_error="\n".join(problems) if problems else None,
    )


# --- 정규화 ---------------------------------------------------------------


def _as_str(value: Any) -> str | None:
    """문자열만 받는다. LLM 이 다른 타입을 내면 NULL 로 두고 raw_json 에 맡긴다."""
    return value if isinstance(value, str) else None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _as_of_datetime(target_date: date | None, raw: Any) -> datetime | None:
    """날짜 "YYYY-MM-DD" 와 시각 "HH:MM" 을 합쳐 KST aware datetime 으로 만든다.

    날짜가 없으면 합칠 수 없어 NULL 이다. 원본 "15:30" 은 raw_json 에 남아 있으므로
    여기서 놓쳐도 되살릴 수 있다.
    """
    if target_date is None or not isinstance(raw, str):
        return None
    try:
        hhmm = time.fromisoformat(raw.strip())
    except ValueError:
        return None
    return datetime.combine(target_date, hhmm, tzinfo=KST)


def _as_decimal(value: Any) -> Decimal | None:
    """등락률. float 를 str 로 한 번 거쳐 Decimal 로 만든다.

    Decimal(3.37) 은 3.3700000000000001... 이 되지만 Decimal("3.37") 은 3.37 이다.
    루트 CLAUDE.md 가 가공하지 않은 값을 요구하므로 적재가 값을 흔들면 안 된다.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_kst_datetime(value: Any) -> datetime | None:
    """출처의 게시 시각. 오프셋이 없으면 KST 로 본다(텔레그램 수집이 KST 기준이다)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def normalize_background(raw: Any) -> dict[str, list[dict[str, Any]]] | None:
    """background 항목의 문자열/객체 혼용을 흡수한다.

    프롬프트는 같은 칸에 `"..."` 와 `{"text": "...", "watch": true}` 를 섞어 낸다.
    **둘 다 정상값이다.** 모델에게 일관성을 요구하는 대신(그러려면 프롬프트를 고쳐야
    하는데 검증 스크립트와 짝이라 못 건드린다) 적재가 `{text, watch}` 로 편다.
    화면이 매번 타입을 확인하지 않아도 되고, 원본 혼용은 raw_json 에 남는다.
    """
    if not isinstance(raw, dict):
        return None

    out: dict[str, list[dict[str, Any]]] = {}
    for slot in BACKGROUND_SLOTS:
        items = raw.get(slot)
        if not isinstance(items, list):
            out[slot] = []
            continue
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                normalized.append({"text": item, "watch": False})
            elif isinstance(item, dict):
                normalized.append(
                    {"text": _as_str(item.get("text")), "watch": bool(item.get("watch", False))}
                )
            # 문자열도 객체도 아니면 버린다. 원본은 raw_json 에 있다.
        out[slot] = normalized
    return out


def normalize_terms(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    return [
        {"plain": _as_str(t.get("plain")), "term": _as_str(t.get("term"))}
        for t in raw
        if isinstance(t, dict)
    ]


def normalize_not_found(raw: Any) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    return [n for n in raw if isinstance(n, str)]


def _log_limit_violations(run_id: str | None, report: dict[str, Any]) -> None:
    """상한 초과를 로그로만 남긴다. 자르지 않는다."""
    factors = report.get("factors")
    if isinstance(factors, list) and len(factors) > MAX_FACTORS:
        logger.warning("%s: factors %d개 (상한 %d)", run_id, len(factors), MAX_FACTORS)

    terms = report.get("terms")
    if isinstance(terms, list) and len(terms) > MAX_TERMS:
        logger.warning("%s: terms %d개 (상한 %d)", run_id, len(terms), MAX_TERMS)

    background = report.get("background")
    if isinstance(background, dict):
        total = 0
        for slot in BACKGROUND_SLOTS:
            items = background.get(slot)
            if not isinstance(items, list):
                continue
            total += len(items)
            if len(items) > MAX_BACKGROUND_PER_SLOT:
                logger.warning(
                    "%s: background.%s %d개 (칸당 상한 %d)",
                    run_id,
                    slot,
                    len(items),
                    MAX_BACKGROUND_PER_SLOT,
                )
        if total > MAX_BACKGROUND_TOTAL:
            logger.warning(
                "%s: background 전체 %d개 (상한 %d)", run_id, total, MAX_BACKGROUND_TOTAL
            )


def build_report(
    parsed: ParsedReport,
    *,
    verify_status: str = "not_verified",
    verify_error: str | None = None,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
    source: str = "telegram",
) -> StockMoveReport:
    """ParsedReport → 아직 DB 에 넣지 않은 ORM 객체.

    `verify_status` 는 **인자다.** 이 함수가 근거 검증을 수행하지 않는다 —
    판정과 적재를 분리해야 한쪽을 고쳐도 다른 쪽이 안 흔들린다.
    """
    r = parsed.report
    _log_limit_violations(parsed.run_id, r)

    target_date = _as_date(r.get("date"))
    summary = r.get("summary") if isinstance(r.get("summary"), dict) else {}

    report = StockMoveReport(
        run_id=parsed.run_id,
        ticker=_as_str(r.get("ticker")),
        name=_as_str(r.get("name")),
        target_date=target_date,
        as_of=_as_of_datetime(target_date, r.get("as_of")),
        change_pct=_as_decimal(r.get("change_pct")),
        verdict=_as_str(r.get("verdict")),
        summary_move=_as_str(summary.get("move")),
        summary_main_cause=_as_str(summary.get("main_cause")),
        # counter 는 null 이 정상값이다(방향이 어긋나는 재료가 없는 날).
        # 빈 문자열로 바꾸지 않는다 — 화면이 "없음" 과 "못 채움" 을 구분해야 한다.
        summary_counter=_as_str(summary.get("counter")),
        summary_unexplained=_as_str(summary.get("unexplained")),
        terms=normalize_terms(r.get("terms")),
        background=normalize_background(r.get("background")),
        not_found=normalize_not_found(r.get("not_found")),
        raw_json=parsed.raw_json,
        parse_status=parsed.parse_status,
        parse_error=parsed.parse_error,
        verify_status=verify_status,
        verify_error=verify_error,
        prompt_version=prompt_version,
        generated_at=generated_at,
    )

    factors = r.get("factors")
    if isinstance(factors, list):
        for i, f in enumerate(factors):
            if not isinstance(f, dict):
                continue
            report.factors.append(_build_factor(i, f, source=source))
    return report


def _build_factor(index: int, f: dict[str, Any], *, source: str) -> StockMoveReportFactor:
    factor = StockMoveReportFactor(
        order_index=index,
        claim=_as_str(f.get("claim")),
        detail=_as_str(f.get("detail")),
        stance=_as_str(f.get("stance")),
        direction_match=_as_bool(f.get("direction_match")),
        size_fit=_as_str(f.get("size_fit")),
        unconfirmed=_as_bool(f.get("unconfirmed")),
    )
    sources = f.get("sources")
    if isinstance(sources, list):
        for j, s in enumerate(sources):
            if not isinstance(s, dict):
                continue
            factor.sources.append(
                StockMoveReportFactorSource(
                    order_index=j,
                    source=source,
                    channel=_as_str(s.get("channel")),
                    url=_as_str(s.get("url")),
                    datetime_kst=_parse_kst_datetime(s.get("datetime_kst")),
                    quote=_as_str(s.get("quote")),
                    match=_as_str(s.get("match")),
                    is_market_recap=_as_bool(s.get("is_market_recap")),
                )
            )
    return factor


# --- 적재 -----------------------------------------------------------------


async def insert_report(
    session: AsyncSession,
    parsed: ParsedReport,
    *,
    verify_status: str = "not_verified",
    verify_error: str | None = None,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
    source: str = "telegram",
) -> StockMoveReport:
    """보고서 한 회차를 넣는다. **INSERT only — 기존 행을 찾지도, 고치지도 않는다.**

    같은 (ticker, target_date, as_of) 가 이미 있어도 새 행으로 쌓는다. 프롬프트가
    "이전 회차를 언급하지 않는다" 고 규정해 각 회차가 독립 문서라서다. 덮어쓰면
    "그때 무엇을 내보냈나" 를 되짚을 수 없다.
    """
    report = build_report(
        parsed,
        verify_status=verify_status,
        verify_error=verify_error,
        generated_at=generated_at,
        prompt_version=prompt_version,
        source=source,
    )
    session.add(report)
    await session.flush()
    return report


async def insert_report_files(
    session: AsyncSession,
    paths: list[Path],
    *,
    verdicts: dict[str, tuple[str, str | None]] | None = None,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
) -> list[StockMoveReport]:
    """parsed/*.json 여러 개를 한 트랜잭션으로 넣는다.

    `verdicts` 는 run_id → (verify_status, verify_error) 다. 검증기 결과를 **받아서**
    채우는 자리이며 없으면 전부 not_verified 로 들어간다. 연결은 후속 PR 이다.
    커밋은 부르는 쪽이 한다 — 배치가 어디까지를 한 단위로 볼지는 여기서 정할 일이 아니다.
    """
    verdicts = verdicts or {}
    inserted: list[StockMoveReport] = []
    for path in paths:
        parsed = parse_report_file(path)
        status, error = verdicts.get(parsed.run_id or "", ("not_verified", None))
        if parsed.parse_status != "ok":
            # 버리지 않는다. 원인 분석 자료가 사라진다.
            logger.warning("%s: %s — %s", path.name, parsed.parse_status, parsed.parse_error)
        inserted.append(
            await insert_report(
                session,
                parsed,
                verify_status=status,
                verify_error=error,
                generated_at=generated_at,
                prompt_version=prompt_version,
            )
        )
    return inserted


__all__ = [
    "KST",
    "ParsedReport",
    "build_report",
    "insert_report",
    "insert_report_files",
    "normalize_background",
    "normalize_not_found",
    "normalize_terms",
    "parse_report_file",
    "parse_wrapper",
]
