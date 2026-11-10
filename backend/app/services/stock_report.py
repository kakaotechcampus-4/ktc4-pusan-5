"""종목 변동 요인 보고서 조회. ai 가 적재한 `raw_json`(보고서 본문)을 응답 계약으로 옮긴다.

보고서는 장 마감 기준으로 미리 만들어 둔 것을 읽기만 한다. 요청 시점에 생성하거나 외부 호출을 하지 않는다.

- 행이 없으면 `pending`(아직 생성 전). 적재는 했지만 근거가 없어 "원인 확인 안 됨" 으로 나온 보고서는 `ready` 다.
- 표를 읽을 수 없거나(ai 마이그레이션 미적용) 본문이 계약과 맞지 않으면 `unavailable`.
  LLM 이 만든 JSON 을 그대로 믿지 않고 Pydantic 으로 검증한 뒤 내려준다.
- `quote`(원문 인용)는 응답 모델에 없으므로 raw_json 에 있어도 나가지 않는다.
"""

import json
import logging
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.core.mvp_stocks import MVP_CODES
from app.repositories.concept import normalize_term
from app.repositories.stock_report import ReportRow, ReportStoreUnavailable, StockReportRepository
from app.schemas.stock import Resource
from app.schemas.stock_report import ReportList, ReportListItem, StockReport

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _factor(raw: Any) -> Any:
    """옛 형식(links 없이 claim·size_fit·direction_match 가 factor 에 직접 있음)을 새 형식으로 옮긴다."""
    if not isinstance(raw, dict):
        return raw
    factor = dict(raw)
    if "event" not in factor and "claim" in factor:
        factor["event"] = factor["claim"]
    if "links" not in factor and (factor.get("size_fit") or "direction_match" in factor):
        factor["links"] = [
            {
                "layer": factor.get("layer") or "move",
                "note": None,
                "direction_match": factor.get("direction_match"),
                "strength": factor.get("size_fit"),
            }
        ]
    return factor


def _as_of(row: ReportRow, report: dict[str, Any]) -> datetime | None:
    if row.as_of is not None:
        return row.as_of
    # 적재 때 날짜를 못 읽어 NULL 이 된 행. 원본의 "HH:MM" 과 날짜를 KST 로 합친다.
    try:
        day = row.target_date or date.fromisoformat(report["date"])
        hh, mm = str(report["as_of"]).split(":")
        return datetime.combine(day, time(int(hh), int(mm)), tzinfo=KST)
    except (KeyError, ValueError, TypeError):
        return None


def to_report(row: ReportRow) -> StockReport | None:
    report = _as_dict(row.raw_json)
    if report is None:
        return None
    as_of = _as_of(row, report)
    if as_of is None:
        return None
    try:
        return StockReport.model_validate(
            {
                "id": row.id,
                "code": row.ticker,
                "name": row.name or report.get("name"),
                "as_of": as_of,
                "change_pct": float(row.change_pct) if row.change_pct is not None else None,
                "generated_at": row.generated_at,
                "verdict": report.get("verdict"),
                "relative_verdict": report.get("relative_verdict"),
                "summary": report.get("summary") or {},
                "factors": [_factor(f) for f in report.get("factors") or []],
                "terms": report.get("terms") or [],
                "background": report.get("background") or {},
            }
        )
    except ValidationError:
        logger.warning("보고서 본문이 응답 계약과 맞지 않습니다 id=%s", row.id, exc_info=True)
        return None


def link_concepts(report: StockReport, term_index: dict[str, str]) -> StockReport:
    """용어 풀이의 각 용어를 개념 글(이름·별칭이 같은 것)에 연결한다."""
    for item in report.terms:
        item.concept_slug = term_index.get(normalize_term(item.term))
    return report


def headline(report: StockReport) -> str | None:
    return report.summary.main_cause or report.summary.move


def source_channels(report: StockReport) -> list[str]:
    """보고서 사건들의 출처 채널. 중복은 처음 나온 순서로 한 번만."""
    channels: dict[str, None] = {}
    for factor in report.factors:
        for source in factor.sources:
            if source.channel:
                channels.setdefault(source.channel)
    return list(channels)


async def list_reports(repository: StockReportRepository, limit: int) -> ReportList:
    try:
        # 종목 상세가 열리는 종목만. 목록 밖 종목 카드는 눌러도 404 화면으로 가기 때문이다.
        rows = await repository.latest_per_stock(limit, MVP_CODES)
    except ReportStoreUnavailable:
        return ReportList(items=[])
    items = []
    for row in rows:
        report = to_report(row)
        if report is None:
            continue
        items.append(
            ReportListItem(
                id=report.id,
                code=report.code,
                name=report.name,
                as_of=report.as_of,
                change_pct=report.change_pct,
                generated_at=report.generated_at,
                verdict=report.verdict,
                headline=headline(report),
            )
        )
    return ReportList(items=items)


async def get_report(
    repository: StockReportRepository, code: str, term_index: dict[str, str] | None = None
) -> Resource[StockReport]:
    try:
        row = await repository.latest_passed(code)
    except ReportStoreUnavailable:
        return Resource[StockReport](status="unavailable")
    if row is None:
        return Resource[StockReport](status="pending")
    report = to_report(row)
    if report is None:
        return Resource[StockReport](status="unavailable")
    link_concepts(report, term_index or {})
    return Resource[StockReport](
        status="ready",
        data=report,
        source_as_of=report.as_of,
        collected_at=row.loaded_at,
    )
