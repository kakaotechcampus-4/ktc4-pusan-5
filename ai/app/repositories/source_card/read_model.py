"""get_sources 가 돌려주는 모양과 조립. 이미 읽은 행만 받고 DB 를 열지 않는다.

시각 이름은 패키지 설명(__init__.py)에, 본문·요약을 언제 주는지는 query.py 에 있다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.scope import KST
from app.models import AnalystReport, Channel, DartDisclosure, News, SourceCard, TelegramMessage

# 원문 표의 경로 값을 사람이 읽는 수집 경로로. 자료 형태(card_type)·원 발행처(source_name)와
# 다른 정보다. 증권사 PDF 를 텔레그램에서 받았다면 pdf · 증권사 · telegram_attachment 다.
COLLECTION_PATHS = {
    ("news", "naver"): "naver_news_search",
    ("news", "telegram"): "telegram_link",
    ("pdf", "naver"): "naver_research",
    ("pdf", "telegram"): "telegram_attachment",
    ("message", "web"): "telegram_web",
    ("message", "telethon"): "telegram_client",
    ("disclosure", "dart"): "dart_list",
}


@dataclass
class Discovery:
    """텔레그램 메시지에서 자료를 발견한 기록 하나. 메시지 쪽에서 보면 그 메시지가 건 링크다."""

    message_card_id: int | None  # 메시지의 공통 ID (등록 전이면 None)
    channel: str
    message_url: str
    posted_at: datetime | None
    kind: str  # url | attachment
    discovered_url: str | None  # 메시지에 적힌 주소 그대로
    final_url: str | None  # 따라가 도착한 주소
    status: str
    target_card_id: int | None  # 이어진 기사·PDF 의 공통 ID


@dataclass
class SourceRecord:
    """공통 ID 하나로 읽은 원문. 형태·발행처·수집 경로를 따로 둔다."""

    id: int  # 공통 자료 ID (source_card.id)
    kind: str  # 자료 형태: news | pdf | message | disclosure
    raw_id: int  # 원문 표의 id
    title: str | None
    url: str | None  # 원문 주소
    # 원 발행처: 기사는 도메인, PDF 는 증권사, 메시지는 채널 이름(전달된 글이면 원래 채널),
    # 공시는 제출인
    publisher: str | None
    collection_path: str  # 수집 경로 (COLLECTION_PATHS)
    channel: str | None  # 텔레그램에서 온 자료의 채널
    published_at: datetime | None  # 기사 발행 시각·메시지 게시 시각. 모르면 None
    write_date: date | None  # PDF 작성일·공시 접수일 (시각이 없다)
    collected_at: datetime | None  # 원문 행을 처음 저장한 시각. 공시는 first_seen_at
    # 공개돼 있었다고 확인된 가장 이른 시각(source_card.available_at). 자료를 고를 때 기준
    # 시각과 비교한다(stock_card_ids)
    available_at: datetime | None
    has_body: bool  # 본문이 있는가 (include_body 와 상관없이 알려준다)
    # 본문이 없으면 그 사유. 있으면 None.
    #   failed: <사유>   열었지만 본문을 못 얻었다 (기사)
    #   empty·unusable·pending·skipped·failed  PDF 본문 상태 그대로 (analyst_reports)
    #   empty            글자 없이 첨부만 올린 메시지
    #   not_collected    본문을 받지 않는 자료 (공시는 목록만 저장한다)
    #   purged: ...      보관 정책으로 지웠다. 재분류·과거 결과 검증에 쓸 수 없다
    #   not_observed_at_cutoff: ...  본문은 있지만 기준 시각 이후에 받았다(또는 받은 시각을
    #                    모른다). get_sources 에 cutoff 를 줬을 때만
    body_missing_reason: str | None
    body_status: str | None  # 원문 표의 상태 값 그대로 (기사 ok|failed|purged, PDF ok|empty|...)
    body_error: str | None
    # 우리가 본문을 받은 시각. 발행 시각 아님. 메시지는 collected_at. 본문을 쓸 때 기준 시각과
    # 비교한다(hide_after_cutoff)
    body_fetched_at: datetime | None
    # 요약. 본문 아님. 기사·네이버 리포트는 네이버가 준 것, 텔레그램 리포트는 생성한 것
    # (collectors/summary.py). get_sources 에 cutoff 를 주면 늘 None
    summary: str | None
    body: str | None = None  # 저장된 정제 본문. 네이버 기사는 최대 3000자. include_body=True만
    edited: bool | None = None  # 메시지만: 수정 표시가 있었다
    edit_detected_at: datetime | None = None  # 메시지만: 다시 수집했을 때 본문이 달랐던 첫 시각
    forwarded_from_url: str | None = None  # 메시지만: 전달된 글이면 원글 주소
    discoveries: list[Discovery] = field(default_factory=list)


def _purged(purged_at: datetime | None, reason: str | None) -> str:
    when = f"{purged_at:%Y-%m-%d}" if purged_at else "시각 미상"
    return f"purged: 보관 정책으로 삭제 ({when}) {reason or ''}".rstrip()


def news_record(card: SourceCard, news: News, has_body: bool, include_body: bool) -> SourceRecord:
    missing = None if has_body else (
        _purged(news.purged_at, news.purge_reason) if news.body_status == "purged"
        else f"failed: {news.body_error or '사유 미기록'}")
    return SourceRecord(
        id=card.id, kind="news", raw_id=news.id, title=news.title or None, url=news.url,
        publisher=news.publisher,
        collection_path=COLLECTION_PATHS.get(("news", news.source), news.source),
        channel=None, published_at=news.published_at, write_date=None,
        collected_at=news.collected_at, available_at=card.available_at, has_body=has_body,
        body_missing_reason=missing,
        body_status=news.body_status, body_error=news.body_error,
        body_fetched_at=news.body_fetched_at, summary=news.summary or None,
        body=news.cleaned_text if include_body else None,
    )


def pdf_record(
    card: SourceCard, report: AnalystReport, has_body: bool, include_body: bool,
) -> SourceRecord:
    telegram = report.source == "telegram"
    missing = None if has_body else (
        _purged(report.purged_at, report.purge_reason) if report.body_status == "purged"
        else report.body_status + (f": {report.body_error}" if report.body_error else ""))
    return SourceRecord(
        id=card.id, kind="pdf", raw_id=report.id, title=report.title,
        url=report.end_url or report.attach_url, publisher=report.broker,
        collection_path=COLLECTION_PATHS.get(("pdf", report.source), report.source),
        channel=report.source_category if telegram else None, published_at=None,
        write_date=report.write_date, collected_at=report.collected_at,
        available_at=card.available_at, has_body=has_body,
        body_missing_reason=missing, body_status=report.body_status,
        body_error=report.body_error, body_fetched_at=report.body_fetched_at,
        summary=report.summary_text, body=report.body_text if include_body else None,
    )


def message_record(
    card: SourceCard, message: TelegramMessage, channel: Channel, has_body: bool, include_body: bool
) -> SourceRecord:
    if message.purged_at is not None:
        status, missing = "purged", _purged(message.purged_at, message.purge_reason)
    else:
        status = "ok" if has_body else "empty"
        missing = None if has_body else "empty: 글자 없이 첨부만 올린 메시지"
    return SourceRecord(
        id=card.id, kind="message", raw_id=message.id, title=None, url=message.url,
        publisher=message.forwarded_from or channel.name,
        collection_path=COLLECTION_PATHS.get(("message", message.collected_via),
                                             message.collected_via),
        channel=channel.telegram_handle, published_at=message.posted_at, write_date=None,
        collected_at=message.collected_at, available_at=card.available_at, has_body=has_body,
        body_missing_reason=missing,
        body_status=status, body_error=None, body_fetched_at=message.collected_at, summary=None,
        body=message.text if include_body else None, edited=message.edited,
        edit_detected_at=message.edit_detected_at,
        forwarded_from_url=message.forwarded_from_url,
    )


def disclosure_record(card: SourceCard, disclosure: DartDisclosure) -> SourceRecord:
    return SourceRecord(
        id=card.id, kind="disclosure", raw_id=disclosure.id, title=disclosure.report_nm,
        url=disclosure.url, publisher=disclosure.flr_nm,
        collection_path=COLLECTION_PATHS[("disclosure", "dart")], channel=None,
        published_at=None, write_date=disclosure.rcept_dt, collected_at=disclosure.first_seen_at,
        available_at=card.available_at, has_body=False,
        body_missing_reason="not_collected: 공시는 목록(제목·제출인·접수일)만 저장한다",
        body_status=None, body_error=None, body_fetched_at=None, summary=None,
    )


def body_observed_by(record: SourceRecord, cutoff: datetime) -> bool:
    """본문을 cutoff 까지 받았다고 확인되는가. 받은 시각을 모르면 아니다."""
    fetched = record.body_fetched_at
    return fetched is not None and fetched <= cutoff


def hide_after_cutoff(record: SourceRecord, cutoff: datetime) -> None:
    """기준 시각에 볼 수 있었다고 확인되지 않는 본문·요약을 뺀다. 저장된 원문은 그대로 둔다.

    본문과 요약은 남은 시각 기록이 달라 규칙이 다르다.
        본문  body_fetched_at 을 cutoff 와 비교한다. 그 뒤에 받았거나 받은 시각을 모르면 뺀다 —
              이전에 받았다고 할 수 없다. 원래 본문이 없던 자료는 그 사유를 그대로 둔다
        요약  나중에 채우거나 덮어쓰는데(news.summary·analyst_reports.summary_text) 그 시각을
              남기지 않는다. 비교할 시각이 없어 늘 뺀다
    제목·주소·시각 같은 메타데이터는 남긴다.
    """
    record.summary = None
    if not record.has_body or body_observed_by(record, cutoff):
        return
    fetched = record.body_fetched_at
    when = f"{fetched.astimezone(KST):%Y-%m-%d %H:%M} KST" if fetched else "받은 시각 미상"
    record.has_body, record.body = False, None
    record.body_missing_reason = f"not_observed_at_cutoff: 기준 시각 이후 받은 본문 ({when})"


def discovery(link, message, channel, message_card_id, target_card_id) -> Discovery:
    return Discovery(
        message_card_id=message_card_id, channel=channel.telegram_handle, message_url=message.url,
        posted_at=message.posted_at, kind=link.kind, discovered_url=link.discovered_url,
        final_url=link.final_url, status=link.status, target_card_id=target_card_id,
    )
