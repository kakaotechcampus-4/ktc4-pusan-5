"""분류 결과 → 보고서 러너 입력(stock_analysis_io.md 1절). 로컬 시험용 어댑터다.

    uv run python -m app.services.stock_analysis.classified_input \\
        --code 005930 --cutoff 2026-11-02T15:30:00+09:00 --change-pct -1.2 --out runs/classified_inputs

    <out>/<code>-<target_date>-<HHMM>.json        러너 입력. 러너에 --input <out> 으로 넘긴다
    <out>/meta/<code>-<target_date>-<HHMM>.json   어느 자료에서 왔는지, 뺀 자료와 그 사유

같은 이름이 있으면 덮어쓴다. meta 를 따로 두는 이유: model_input() 은 맨 위 칸과 메시지 칸을 모두 모델에
보내므로 입력에는 규격 밖 키(source_card_id 등)를 넣지 않는다. 또 러너는 --input 폴더 바로 아래 *.json 을 모두
입력으로 읽어서, 같은 폴더에 두면 check_input 에 걸려 실행이 멈춘다.

## 자료 고르기

classified_sources(code, until=cutoff, since) 에서 텔레그램 메시지 카드만 쓴다. 뉴스·PDF 카드(네이버 경로,
텔레그램 링크로 받은 기사)는 이번엔 넣지 않는다. 본문은 get_sources(include_body=True, cutoff=cutoff) 로 읽고,
본문이 없는 메시지(첨부만·보관 정책으로 지움·기준 시각 뒤에 받음)는 빼고 meta 에 사유를 남긴다.

## 메시지 칸

    mention     이 종목 사건 중 path = company 가 하나라도 있으면 mentioned, 아니면 not_mentioned.
                판정(label)·card_label 은 보지 않는다 — company 경로면 INDIRECT_CONTEXT 판정이어도 mentioned
    kind        공통 배경만 있는 메시지(이 종목 사건이 macro·market 뿐, card_label = null)는 market_recap 이라
                market_context 칸으로 간다. 기준 시각에 가까운 MARKET_RECAP_LIMIT(3)건만 남기고 뺀 수는 meta 에.
                company·industry·relation 사건이 있는 메시지는 other(messages 칸)
    after_prev_close   false. 전날 장 시황인지 가릴 정보가 없다
    first_seen_kst / dup_channels   묶음 정보(bundle_of). 없으면 null / 1
    views·link_bodies  넣지 않는다. 조회수는 DB 에 없고, 링크 기사는 이번 범위(메시지만) 밖이다

## 조회 시작(since)

주지 않으면 target_date 직전 거래일의 장 마감 시각(market_compare.market_close — 평소 15:30, LATE_CLOSE 날은 그
시각)이다. backend 가 같은 DB 에 두는 market_calendar(KIS 휴장일조회)로 거래일을 가린다. 행이 없는 날은 backend
(TradingCalendar.is_open_day)와 같이 평일을 개장일로 본다. **표를 읽을 수 없으면 직전 평일의 장 마감으로 둔다.
이때 휴장일 다음 날은 휴장일 장 마감 시각부터 보게 되어, 그 전 거래일 장 마감 뒤부터 휴장일 장 마감까지의
메시지가 빠질 수 있다**(예: 월요일이 휴장이면 화요일 보고서에 금요일 15:30 ~ 월요일 15:30 메시지가 없다).
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import KST
from app.repositories.classification import classified_sources
from app.repositories.source_card import get_sources
from app.repositories.source_card.read_model import SourceRecord
from app.services.stock_analysis import stock_meta
from app.services.stock_analysis.market_compare import market_close

MESSAGE_CARD_TYPE = "message"
MENTIONED_PATH = "company"
EVIDENCE_KIND = "other"
COMMON_KIND = "market_recap"
# 공통 배경 메시지를 몇 건까지 넣는가(stock_analysis_io.md 「러너가 호출 전에 보는 것」의 시장 시황 최대 3건)
MARKET_RECAP_LIMIT = 3
# 직전 거래일을 찾아 거슬러 올라가는 최대 일수. backend market_calendar.MAX_LOOKBACK_DAYS 와 같다
MAX_LOOKBACK_DAYS = 30
# classified_sources 자료에 묶음 정보가 붙으면 읽을 칸. 이름은 임시다 — 묶음 칸이 생기면 bundle_of 만 맞춘다
BUNDLE_KEY = "bundle"


# ── 조회 시작 ──────────────────────────────────────────────────────────────

def previous_close(day: date, open_days: Mapping[date, bool] | None = None) -> datetime:
    """day 직전 거래일의 장 마감 시각(KST). open_days 에 없는 날은 평일을 개장일로 본다."""
    days = open_days or {}
    for offset in range(1, MAX_LOOKBACK_DAYS + 1):
        candidate = day - timedelta(days=offset)
        if days.get(candidate, candidate.weekday() < 5):
            return datetime.combine(candidate, market_close(candidate), tzinfo=KST)
    # 한 달 내내 휴장이라는 달력은 저장 값이 틀린 것이다. 평일로 돌아간다(backend 와 같다)
    return previous_close(day)


async def read_open_days(session: AsyncSession, day: date) -> dict[date, bool] | None:
    """market_calendar 의 day 이전 MAX_LOOKBACK_DAYS 일 개장 여부. 표가 없거나 못 읽으면 None.

    backend 표라 ai 쪽 모델이 없어 SQL 로 읽는다. 실패해도 세션의 트랜잭션을 깨지 않게 savepoint 안에서 읽는다.
    """
    try:
        async with session.begin_nested():
            rows = (await session.execute(
                text("SELECT day, is_open FROM market_calendar WHERE day >= :start AND day < :day"),
                {"start": day - timedelta(days=MAX_LOOKBACK_DAYS), "day": day},
            )).all()
    except SQLAlchemyError:
        return None
    return {row[0]: row[1] for row in rows}


# ── 입력 만들기 ────────────────────────────────────────────────────────────

def _kst(value: datetime | None) -> str | None:
    return value.astimezone(KST).isoformat(timespec="seconds") if value else None


def bundle_of(source: dict[str, Any], since: datetime) -> tuple[str | None, int]:
    """(first_seen_kst, dup_channels). 묶음 정보가 없으면 (None, 1).

    first_seen_kst 는 프롬프트가 "전날부터 이어진 재료" 로 읽으므로, 묶음에서 처음 나온 시각이 조회 시작(since)
    보다 앞설 때만 넣는다.
    """
    bundle = source.get(BUNDLE_KEY)
    if not bundle:
        return None, 1
    first = bundle.get("first_seen_at")
    if isinstance(first, str):
        first = datetime.fromisoformat(first)
    return (_kst(first) if first is not None and first < since else None), bundle.get("dup_channels", 1)


def build_input(
    found: dict[str, Any], records: Mapping[int, SourceRecord], *, code: str, cutoff: datetime,
    change_pct: float, since: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(러너 입력, meta). found 는 classified_sources 결과, records 는 그 메시지 카드의 get_sources(include_body=True)."""
    name = stock_meta.name(code)
    if name is None:
        raise ValueError(f"stock_meta.json 에 없는 종목: {code}")

    evidence, common, dropped = [], [], []
    skipped_types: dict[str, int] = {}
    position = {s["source_card_id"]: n for n, s in enumerate(found["sources"])}
    for source in found["sources"]:
        card_id = source["source_card_id"]
        if source["card_type"] != MESSAGE_CARD_TYPE:
            skipped_types[source["card_type"]] = skipped_types.get(source["card_type"], 0) + 1
            continue
        record = records.get(card_id)
        if record is None or not record.has_body:
            dropped.append({"source_card_id": card_id, "reason": record.body_missing_reason
                            if record else "get_sources 에 없음"})
            continue
        is_common = source["card_label"] is None
        first_seen, dup_channels = bundle_of(source, since)
        message = {
            "channel": record.channel,
            "url": record.url,
            "datetime_kst": _kst(record.published_at or record.available_at),
            "text": record.body,
            "mention": "mentioned" if any(e["path"] == MENTIONED_PATH for e in source["events"])
                       else "not_mentioned",
            "kind": COMMON_KIND if is_common else EVIDENCE_KIND,
            "after_prev_close": False,
            "first_seen_kst": first_seen,
            "dup_channels": dup_channels,
        }
        trace = {"source_card_id": card_id, "url": record.url, "card_label": source["card_label"],
                 "paths": sorted({e["path"] for e in source["events"]}), "kind": message["kind"],
                 "mention": message["mention"]}
        (common if is_common else evidence).append((message, trace))

    # 공통 배경은 기준 시각에 가까운 것만 남긴다. 남긴 것은 원래 순서(오래된 순) 그대로다
    keep = set(sorted(range(len(common)), key=lambda i: common[i][0]["datetime_kst"] or "",
                      reverse=True)[:MARKET_RECAP_LIMIT])
    common_kept = [item for i, item in enumerate(common) if i in keep]
    no_body = len(dropped)
    dropped += [{"source_card_id": trace["source_card_id"],
                 "reason": f"공통 배경 {MARKET_RECAP_LIMIT}건 초과"}
                for i, (_, trace) in enumerate(common) if i not in keep]

    # 메시지는 classified_sources 순서(오래된 순)다. split_messages 가 칸 안에서 이 순서를 지킨다
    used = sorted(evidence + common_kept, key=lambda item: position[item[1]["source_card_id"]])

    payload = {
        "stock": name, "code": code,
        "target_date": cutoff.astimezone(KST).date().isoformat(),
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "change_pct": change_pct,
        "market": None,
        "messages": [message for message, _ in used],
    }
    meta = {
        "code": code, "cutoff": payload["cutoff"], "since": since.isoformat(timespec="seconds"),
        "messages": [trace for _, trace in used],
        "counts": {
            "sources": len(found["sources"]), "messages": len(used),
            "evidence": len(evidence), "market_recap": len(common_kept),
            "market_recap_dropped": len(common) - len(common_kept),
            "no_body": no_body,
            "skipped_card_types": skipped_types,
        },
        "dropped": dropped,
        "unclassified": found["unclassified"], "failed": found["failed"],
        "not_observed": found["not_observed"],
    }
    return payload, meta


async def load_input(
    session: AsyncSession, code: str, *, cutoff: datetime, change_pct: float,
    since: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """DB 에서 읽어 (러너 입력, meta). since 를 안 주면 직전 거래일 장 마감(맨 위 설명)."""
    if cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    if since is not None:
        since_basis = "argument"
    else:
        open_days = await read_open_days(session, cutoff.astimezone(KST).date())
        since_basis = "market_calendar" if open_days is not None else "weekday_fallback"
        since = previous_close(cutoff.astimezone(KST).date(), open_days)
    found = await classified_sources(session, code, until=cutoff, since=since)
    ids = [s["source_card_id"] for s in found["sources"] if s["card_type"] == MESSAGE_CARD_TYPE]
    records = {r.id: r for r in await get_sources(session, ids, include_body=True, cutoff=cutoff)}
    payload, meta = build_input(found, records, code=code, cutoff=cutoff, change_pct=change_pct,
                                since=since)
    meta["since_basis"] = since_basis
    return payload, meta


# ── 실행 ──────────────────────────────────────────────────────────────────

def write(out: Path, payload: dict[str, Any], meta: dict[str, Any]) -> Path:
    cutoff = datetime.fromisoformat(payload["cutoff"]).astimezone(KST)
    filename = f"{payload['code']}-{payload['target_date']}-{cutoff:%H%M}.json"
    (out / "meta").mkdir(parents=True, exist_ok=True)
    path = out / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "meta" / filename).write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return path


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


async def main(args: argparse.Namespace) -> None:
    from app.core.database import SessionLocal

    async with SessionLocal() as session:
        payload, meta = await load_input(
            session, args.code, cutoff=_aware(args.cutoff), change_pct=args.change_pct,
            since=_aware(args.since) if args.since else None)
    path = write(args.out, payload, meta)
    counts = meta["counts"]
    print(f"{path}  since {meta['since']} ({meta['since_basis']})  메시지 {counts['messages']}"
          f" (근거 {counts['evidence']} · 시황 {counts['market_recap']}, 시황 뺌 {counts['market_recap_dropped']})"
          f"  본문 없음 {counts['no_body']}  메시지 밖 {counts['skipped_card_types']}"
          f"  미분류 {meta['unclassified']} · 실패 {meta['failed']} · 기준 시각 뒤 본문 {meta['not_observed']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="분류 결과 → 보고서 러너 입력")
    parser.add_argument("--code", required=True)
    parser.add_argument("--cutoff", required=True, help="기준 시각 ISO 8601. 시간대가 없으면 KST")
    parser.add_argument("--change-pct", type=float, required=True,
                        help="기준 시각 등락률. 장 마감 뒤 KRX 가 ok 면 러너가 덮어쓴다")
    parser.add_argument("--since", help="조회 시작. 없으면 직전 거래일 장 마감")
    parser.add_argument("--out", type=Path, default=Path("runs/classified_inputs"))
    asyncio.run(main(parser.parse_args()))
