"""분류 결과 → 보고서 러너 입력(stock_analysis_io.md 1절). 로컬 시험용 어댑터다.

    uv run python -m app.services.stock_analysis.classified_input \\
        --code 005930 --cutoff 2026-11-02T15:30:00+09:00 --change-pct -1.2 --out runs/classified_inputs

    <out>/<code>-<target_date>-<HHMM>.json        러너 입력. 러너에 --input <out> 으로 넘긴다
    <out>/meta/<code>-<target_date>-<HHMM>.json   어느 자료에서 왔는지, 뺀 자료와 그 사유

같은 이름이 있으면 덮어쓴다. meta 를 따로 두는 이유: model_input() 은 맨 위 칸과 메시지 칸을 모두 모델에
보내므로 입력에는 규격 밖 키(source_card_id 등)를 넣지 않는다. 또 러너는 --input 폴더 바로 아래 *.json 을 모두
입력으로 읽어서, 같은 폴더에 두면 check_input 에 걸려 실행이 멈춘다.

## 자료 고르기

classified_sources(code, until=cutoff, since) 에서 텔레그램 메시지 카드, 뉴스 카드(네이버 검색, 텔레그램 링크로
받은 기사), 증권사 리포트(PDF) 카드를 쓴다. 공시는 분류하지 않으므로 같은 기간에 dart_stock_code 로 이 종목에
이어진 공시 카드(stock_card_ids)를 뒤에 붙인다. 본문은 get_sources(include_body=True, cutoff=cutoff) 로 읽고,
본문이 없는 자료(첨부만·본문 추출 실패·보관 정책으로 지움·기준 시각 뒤에 받음)는 빼고 meta 에 사유를 남긴다.
공시는 목록만 저장해 본문이 없으므로 제목을 text 로 넣는다(kind disclosure, mentioned).
정정 공시(제목이 CORRECTION_RE 로 시작 — [기재정정]·[첨부정정]·[첨부추가])는 is_correction: true 다. 이미 낸 서류를
고친 것이라 그날의 새 사건이 아니다(프롬프트 1부, 검증 경고 DISCLOSURE_CORRECTION_AS_CAUSE). 공시 메시지에만 이 칸이 있다.
뉴스·리포트는 기준 시각 전에 본문을 받아 둔 것만 들어간다(body_fetched_at 기준) — 보고서보다 먼저 수집해야 한다.

## 메시지 칸

뉴스·리포트 카드도 메시지 하나로 넣는다. channel 은 언론사·증권사(publisher), text 는 제목 + 빈 줄 + 본문이다.

    mention     이 종목 사건 중 path = company 가 하나라도 있으면 mentioned, 아니면 not_mentioned.
                판정(label)·card_label 은 보지 않는다 — company 경로면 INDIRECT_CONTEXT 판정이어도 mentioned
    kind        공통 배경만 있는 메시지(이 종목 사건이 macro·market 뿐, card_label = null)는 market_recap 이라
                market_context 칸으로 간다. 기준 시각에 가까운 MARKET_RECAP_LIMIT(3)건만 남기고 뺀 수는 meta 에.
                company·industry·relation 사건이 있는 메시지는 other(messages 칸), 뉴스면 news(messages 칸)
    after_prev_close   false. 전날 장 시황인지 가릴 정보가 없다
    first_seen_kst     묶음 정보(bundle_of). 없으면 null
    dup_channels       아래 중복 묶음에 든 서로 다른 채널 수와 묶음 정보 중 큰 값. 없으면 1
    views·link_bodies  넣지 않는다. 조회수는 DB 에 없고, 링크 기사는 이번 범위(메시지만) 밖이다

## 중복 묶기

본문이 같은 메시지는 하나만 넣는다. 공백을 한 칸으로 줄여 비교하고, 끝이 「…」인 글은 「…」를 뗀 나머지가 다른
글의 앞부분이면 같은 글로 본다(채널이 긴 글을 잘라 다시 올린 경우). 다만 그 나머지로 시작하는 글들이 서로 다른 글이면
(「삼성전자…」 뒤에 실적 기사와 파업 기사) 어느 쪽인지 모르므로 묶지 않는다 — 묶으면 다른 글이 중복으로 빠진다.
대표는 가장 긴 글(같으면 먼저 나온 글)이다.
묶음 안에 company 경로가 하나라도 있으면 mentioned, 근거 칸 메시지가 하나라도 있으면 근거 칸이다(kind 는 대표
자료의 종류대로 other·news). 기사는 제목을 뺀 본문으로 비교해, 기사 본문을 옮긴 텔레그램 메시지와도 묶인다.
나머지는 meta dropped 에 대표 자료 ID 와 함께 남긴다. 공통 배경 MARKET_RECAP_LIMIT 은 묶은 뒤에 센다.

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
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import KST
from app.repositories.classification import classified_sources
from app.repositories.source_card import get_sources, stock_card_ids
from app.repositories.source_card.read_model import SourceRecord
from app.services.stock_analysis import stock_meta
from app.services.stock_analysis.market_compare import market_close

MESSAGE_CARD_TYPE = "message"
NEWS_CARD_TYPE = "news"
PDF_CARD_TYPE = "pdf"
DISCLOSURE_CARD_TYPE = "disclosure"
INPUT_CARD_TYPES = (MESSAGE_CARD_TYPE, NEWS_CARD_TYPE, PDF_CARD_TYPE, DISCLOSURE_CARD_TYPE)
# 정정 공시 제목 머리. DART 보고서명 앞 괄호 표시다. [발행조건확정]·[연장결정] 은 새 결정이라 넣지 않는다
CORRECTION_RE = re.compile(r"^\[(기재정정|첨부정정|첨부추가)\]")
# 제목을 본문 앞에 붙이는 자료(기사·리포트). 공시는 본문이 없어 제목만 넣는다
TITLED_CARD_TYPES = (NEWS_CARD_TYPE, PDF_CARD_TYPE)
MENTIONED_PATH = "company"
EVIDENCE_KIND = "other"
NEWS_KIND = "news"
DISCLOSURE_KIND = "disclosure"
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
    """market_calendar 의 day 이전 MAX_LOOKBACK_DAYS 일 개장 여부. 표가 없거나 못 읽거나 그 기간에 행이 없으면 None.

    backend 표라 ai 쪽 모델이 없어 SQL 로 읽는다. 실패해도 세션의 트랜잭션을 깨지 않게 savepoint 안에서 읽는다.
    행이 없을 때도 None 인 이유: 빈 표로 고른 since 는 평일 규칙으로 고른 것인데 meta 에 market_calendar 로 남는다.
    """
    try:
        async with session.begin_nested():
            rows = (await session.execute(
                text("SELECT day, is_open FROM market_calendar WHERE day >= :start AND day < :day"),
                {"start": day - timedelta(days=MAX_LOOKBACK_DAYS), "day": day},
            )).all()
    except SQLAlchemyError:
        return None
    return {row[0]: row[1] for row in rows} or None


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


def evidence_kind(card_type: str) -> str:
    """근거 칸 메시지의 kind. 뉴스 카드면 news, 공시면 disclosure, 텔레그램 메시지·리포트는 other."""
    return {NEWS_CARD_TYPE: NEWS_KIND, DISCLOSURE_CARD_TYPE: DISCLOSURE_KIND}.get(card_type, EVIDENCE_KIND)


def channel_and_text(card_type: str, record: SourceRecord) -> tuple[str | None, str | None]:
    """(channel, text). 뉴스·리포트는 언론사·증권사와 제목 + 빈 줄 + 본문(제목이 없으면 본문만).
    공시는 제출인과 공시 제목(본문을 받지 않는다)."""
    if card_type == DISCLOSURE_CARD_TYPE:
        return record.publisher, record.title
    if card_type not in TITLED_CARD_TYPES:
        return record.channel, record.body
    text = f"{record.title}\n\n{record.body}" if record.title and record.body else record.body
    return record.publisher, text


def has_text(card_type: str, record: SourceRecord | None) -> bool:
    """메시지로 넣을 글이 있는가. 공시는 제목, 나머지는 본문."""
    if record is None:
        return False
    return bool(record.title) if card_type == DISCLOSURE_CARD_TYPE else record.has_body


def message_time(record: SourceRecord) -> str | None:
    """datetime_kst. 시각을 모르는 리포트·공시는 작성일·접수일(YYYY-MM-DD)."""
    moment = _kst(record.published_at or record.available_at)
    return moment or (record.write_date.isoformat() if record.write_date else None)


def is_correction(title: str | None) -> bool:
    """정정 공시인가. 보고서명이 CORRECTION_RE 로 시작하면 정정이다."""
    return bool(title) and CORRECTION_RE.match(title.strip()) is not None


def disclosure_source(card_id: int) -> dict[str, Any]:
    """공시 카드를 classified_sources 자료 모양으로. 공시는 분류하지 않고(classification.py 맨 위)
    dart_stock_code 로 이 종목에 이어져 있어 회사 사건 하나(company, DIRECT)로 본다."""
    return {"source_card_id": card_id, "card_type": DISCLOSURE_CARD_TYPE, "card_label": "DIRECT",
            "events": [{"path": MENTIONED_PATH, "label": "DIRECT"}]}


def _dedup_key(text: str) -> tuple[str, bool]:
    """(비교할 본문, 끝이 「…」였는가). 공백은 한 칸으로 줄이고 끝의 「…」는 뗀다."""
    normalized = " ".join(text.split())
    trimmed = normalized.rstrip("…").rstrip()
    return trimmed, trimmed != normalized


def same_text(a: str, b: str) -> bool:
    """같은 글인가. 본문이 같거나, 끝이 「…」인 쪽의 나머지가 다른 쪽의 앞부분이다."""
    (key_a, cut_a), (key_b, cut_b) = _dedup_key(a), _dedup_key(b)
    if key_a == key_b:
        return True
    return bool((cut_a and key_a and key_b.startswith(key_a)) or (cut_b and key_b and key_a.startswith(key_b)))


def group_duplicates(texts: list[str]) -> list[list[int]]:
    """같은 글끼리 묶은 위치 목록. 묶음은 첫 위치 순, 묶음 안은 위치 순이다.

    본문(_dedup_key)이 같은 글을 먼저 묶는다. 끝이 「…」인 글은 「…」를 뗀 나머지로 시작하는 다른 본문들이 **모두 한 글의
    앞부분들일 때만**(가장 긴 본문이 나머지 모두로 시작할 때만) 그 본문들과 묶는다. 「A 글…」·「A 글 전체…」·「A 글 전체
    본문」은 한 묶음이고, 「삼성전자…」 뒤에 「삼성전자 3분기 실적…」·「삼성전자 노조 파업…」이 오면 어느 쪽도 묶지 않는다.
    same_text 를 쌍마다 부르면 같은 본문을 몇 번씩 다시 정규화하므로 본문마다 한 번만 계산한다.
    """
    parent = list(range(len(texts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = root(i), root(j)
        if a != b:
            parent[max(a, b)] = min(a, b)

    keys = [_dedup_key(text) for text in texts]
    first: dict[str, int] = {}  # 본문 → 그 본문인 첫 위치
    cut_keys: set[str] = set()  # 끝이 「…」였던 글의 본문
    for i, (key, cut) in enumerate(keys):
        if key in first:
            union(first[key], i)
        else:
            first[key] = i
        if cut and key:
            cut_keys.add(key)
    for key in cut_keys:
        longer = [other for other in first if other != key and other.startswith(key)]
        if not longer:
            continue
        longest = max(longer, key=len)
        if all(longest.startswith(other) for other in longer):
            for other in longer:
                union(first[key], first[other])
    groups: dict[int, list[int]] = {}
    for i in range(len(texts)):
        groups.setdefault(root(i), []).append(i)
    return sorted(groups.values(), key=lambda group: group[0])


class UnknownStockError(ValueError):
    """보고서 종목표(stock_meta.json)에 없는 종목. 수집 범위(예: DART 100종목)가 이 표보다 넓어 생긴다."""


def require_known_stock(code: str) -> str:
    """종목명. 종목표에 없으면 UnknownStockError — DB 를 읽기 전에 부른다."""
    name = stock_meta.name(code)
    if name is None:
        raise UnknownStockError(
            f"stock_meta.json 에 없는 종목: {code}. 보고서는 {stock_meta.META_PATH} 에 있는 종목만 만든다. "
            "종목을 더하려면 그 표(업종·대형주 비중)와 분류 기준 JSON 을 함께 고친다.")
    return name


def build_input(
    found: dict[str, Any], records: Mapping[int, SourceRecord], *, code: str, cutoff: datetime,
    change_pct: float, since: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(러너 입력, meta). found 는 classified_sources 결과, records 는 그 메시지·뉴스 카드의 get_sources(include_body=True)."""
    name = require_known_stock(code)

    items, dropped = [], []  # items: 본문 있는 메시지의 (message, trace), classified_sources 순서
    bodies = []  # items 와 같은 순서의 본문. 중복은 기사 제목을 뺀 본문으로 비교한다
    skipped_types: dict[str, int] = {}
    position = {s["source_card_id"]: n for n, s in enumerate(found["sources"])}
    for source in found["sources"]:
        card_id = source["source_card_id"]
        if source["card_type"] not in INPUT_CARD_TYPES:
            skipped_types[source["card_type"]] = skipped_types.get(source["card_type"], 0) + 1
            continue
        record = records.get(card_id)
        if not has_text(source["card_type"], record):
            dropped.append({"source_card_id": card_id, "reason": record.body_missing_reason
                            if record else "get_sources 에 없음"})
            continue
        is_common = source["card_label"] is None
        first_seen, dup_channels = bundle_of(source, since)
        channel, body = channel_and_text(source["card_type"], record)
        message = {
            "channel": channel,
            "url": record.url,
            "datetime_kst": message_time(record),
            "text": body,
            "mention": "mentioned" if any(e["path"] == MENTIONED_PATH for e in source["events"])
                       else "not_mentioned",
            "kind": COMMON_KIND if is_common else evidence_kind(source["card_type"]),
            "after_prev_close": False,
            "first_seen_kst": first_seen,
            "dup_channels": dup_channels,
        }
        if source["card_type"] == DISCLOSURE_CARD_TYPE:
            message["is_correction"] = is_correction(record.title)
        trace = {"source_card_id": card_id, "card_type": source["card_type"], "url": record.url,
                 "card_label": source["card_label"],
                 "paths": sorted({e["path"] for e in source["events"]}), "kind": message["kind"],
                 "mention": message["mention"], "duplicates": []}
        items.append((message, trace))
        bodies.append(record.body or body)
    no_body = len(dropped)

    # 같은 글은 가장 긴 글 하나로 묶는다(맨 위 「중복 묶기」). max 는 길이가 같으면 먼저 나온 글을 고른다
    evidence, common = [], []
    duplicates = 0
    for group in group_duplicates(bodies):
        members = [items[i] for i in group]
        message, trace = max(members, key=lambda item: len(item[0]["text"]))
        others = [other for _, other in members if other is not trace]
        if others:
            mention = ("mentioned" if any(m["mention"] == "mentioned" for m, _ in members)
                       else "not_mentioned")
            # kind 는 대표 자료의 종류를 따른다 — 기사와 묶인 텔레그램 대표가 news 가 되지 않게
            kind = (evidence_kind(trace["card_type"]) if any(m["kind"] != COMMON_KIND for m, _ in members)
                    else COMMON_KIND)
            message = {**message, "mention": mention, "kind": kind,
                       "dup_channels": max(message["dup_channels"], len({m["channel"] for m, _ in members}))}
            trace = {**trace, "mention": mention, "kind": kind,
                     "duplicates": [other["source_card_id"] for other in others]}
            dropped += [{"source_card_id": other["source_card_id"],
                         "reason": f"중복 — 대표 자료 {trace['source_card_id']}"} for other in others]
            duplicates += len(others)
        (common if message["kind"] == COMMON_KIND else evidence).append((message, trace))

    # 공통 배경은 기준 시각에 가까운 것만 남긴다. 남긴 것은 원래 순서(오래된 순) 그대로다
    keep = set(sorted(range(len(common)), key=lambda i: common[i][0]["datetime_kst"] or "",
                      reverse=True)[:MARKET_RECAP_LIMIT])
    common_kept = [item for i, item in enumerate(common) if i in keep]
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
            "news": sum(trace["card_type"] == NEWS_CARD_TYPE for _, trace in used),
            "pdf": sum(trace["card_type"] == PDF_CARD_TYPE for _, trace in used),
            "disclosure": sum(trace["card_type"] == DISCLOSURE_CARD_TYPE for _, trace in used),
            "market_recap_dropped": len(common) - len(common_kept),
            "no_body": no_body, "duplicates": duplicates,
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
    # 종목표에 없는 종목이면 DB 를 읽어 봐야 입력을 만들 수 없다. 조회 전에 멈춘다
    require_known_stock(code)
    if since is not None:
        since_basis = "argument"
    else:
        open_days = await read_open_days(session, cutoff.astimezone(KST).date())
        since_basis = "market_calendar" if open_days is not None else "weekday_fallback"
        since = previous_close(cutoff.astimezone(KST).date(), open_days)
    found = await classified_sources(session, code, until=cutoff, since=since)
    # 공시는 분류하지 않아 classified_sources 에 없다. 같은 기간에 이 종목으로 이어진 공시 카드를 뒤에 붙인다.
    # 공시만 고르는 건 조회에서 한다 — 이어진 카드를 전부 get_sources 로 읽고 거르면 메시지·기사 카드의 링크·공유
    # 메시지까지 읽게 된다
    disclosures = await stock_card_ids(session, code, until=cutoff, since=since, card_type=DISCLOSURE_CARD_TYPE)
    found["sources"] += [disclosure_source(card_id) for card_id in disclosures]
    ids = [s["source_card_id"] for s in found["sources"] if s["card_type"] in INPUT_CARD_TYPES]
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
          f"  넣은 기사 {counts['news']}  공시 {counts['disclosure']}"
          f"  본문 없음 {counts['no_body']}  중복 뺌 {counts['duplicates']}  메시지 밖 {counts['skipped_card_types']}"
          f"  미분류 {meta['unclassified']} · 실패 {meta['failed']} · 기준 시각 뒤 본문 {meta['not_observed']}")


def cli(argv: list[str] | None = None) -> None:
    """명령줄 진입점. 종목표에 없는 종목은 DB 를 읽기 전에 안내 문구와 exit 1 로 끝낸다."""
    parser = argparse.ArgumentParser(description="분류 결과 → 보고서 러너 입력")
    parser.add_argument("--code", required=True)
    parser.add_argument("--cutoff", required=True, help="기준 시각 ISO 8601. 시간대가 없으면 KST")
    parser.add_argument("--change-pct", type=float, required=True,
                        help="기준 시각 등락률. 장 마감 뒤 KRX 가 ok 면 러너가 덮어쓴다")
    parser.add_argument("--since", help="조회 시작. 없으면 직전 거래일 장 마감")
    parser.add_argument("--out", type=Path, default=Path("runs/classified_inputs"))
    args = parser.parse_args(argv)
    try:
        require_known_stock(args.code)
    except UnknownStockError as exc:
        parser.exit(1, f"{exc}\n")
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
