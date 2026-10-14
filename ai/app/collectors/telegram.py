"""텔레그램 채널의 증권사 리포트 PDF 수집 → 정규화 → DB 저장.

    uv run python -m app.collectors.telegram --days 7
    uv run python -m app.collectors.telegram --days 1 --channel sunstudy1234 --limit 5

네이버 컬렉터(app/collectors/analyst_report.py)와 같은 analyst_reports 테이블에 넣는다.
`source` 로만 갈린다. 테이블·upsert·PDF 추출은 전부 재사용한다.

네이버와 다른 점은 네트워크 비용이다. 네이버는 PDF 가 건당 수백 KB 인데 텔레그램은
평균 3.7MB 다(선진짱 220건 806MB). 그래서 이미 받은 건 반드시 건너뛴다.

PDF 가 붙어 있던 **메시지와 발견 경로**도 남긴다(record_pdf_messages). 메시지는
telegram_messages 에, "이 메시지에서 이 PDF 를 발견했다" 는 telegram_message_links 에 들어간다.
네이버에 같은 PDF 가 있어 텔레그램 행을 만들지 않은 경우에도 그 네이버 행에 발견 경로를 잇는다.
이 기록이 실패해도 같은 묶음의 PDF 행은 저장한다 — PDF 는 다시 받기 비싸다.
"""

import argparse
import asyncio
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.scope import CollectionScope, ScopeError, load_scope
from app.repositories.analyst_report import (
    known_ids,
    known_naver_pdf_hashes,
    upsert_analyst_reports,
)
from app.repositories.scope import collection_locks, count_collected
from app.repositories.source_card import register_missing_sources
from app.repositories.telegram_message import (
    ensure_channels,
    find_attachment_report,
    recorded_attachment_ids,
    save_message_links,
    save_messages,
)
from app.services.analyst.pdf import pdf_text_from_bytes
from app.services.analyst.schema import PdfText
from app.services.analyst.telegram import (
    KST,
    check_channels,
    connect_authorized,
    download_pdf,
    exclusion_reason,
    iter_pdf_messages,
    make_client,
    parse_channel,
    to_row,
)

logger = logging.getLogger(__name__)
SOURCE = "telegram"
COMMIT_EVERY = 20  # 200건짜리 채널에서 중간에 끊겨도 앞은 남게
AUTHOR_MAX_CHARS = 200


@dataclass
class FoundPdf:
    """PDF 가 붙어 있던 메시지 하나. 묶음을 저장할 때 메시지·발견 경로로 남긴다."""

    msg_id: int
    posted_at: datetime | None
    text: str
    author: str | None
    views: str | None
    edited: bool
    filename: str
    pdf_sha256: str | None
    excluded: bool  # 수집 대상이 아니라서(AI 생성 자료 등) PDF 행을 만들지 않았다
    forwarded_from: str | None = None  # 다른 채널 글을 전달한 것이면 원래 채널
    forwarded_from_url: str | None = None


def forward_origin(message: Any) -> tuple[str | None, str | None]:
    """(원래 출처, 원글 주소). 전달된 메시지가 아니면 (None, None).

    Telethon 은 원래 채널을 이름이 아니라 id 로 준다(fwd_from.from_id). 이름을 찾으려면 API 를 한 번
    더 불러야 해서 id 를 그대로 남긴다. 사람에게서 전달된 글은 사용자 id 를 남기지 않는다.
    """
    header = getattr(message, "fwd_from", None)
    if header is None:
        return None, None
    channel_id = getattr(getattr(header, "from_id", None), "channel_id", None)
    post = getattr(header, "channel_post", None)
    url = f"https://t.me/c/{channel_id}/{post}" if channel_id and post else None
    if channel_id:
        return f"channel:{channel_id}", url
    return getattr(header, "from_name", None) or "알 수 없음", url


def found_pdf(message: Any, filename: str, pdf: PdfText, *, excluded: bool = False) -> FoundPdf:
    """Telethon 메시지 → FoundPdf. 캡션이 없거나 값이 없는 메시지도 있어 getattr 로 읽는다."""
    views = getattr(message, "views", None)
    forwarded_from, forwarded_from_url = forward_origin(message)
    return FoundPdf(
        msg_id=message.id,
        posted_at=getattr(message, "date", None),
        text=getattr(message, "message", None) or "",
        author=(getattr(message, "post_author", None) or None),
        views=str(views) if views is not None else None,
        edited=getattr(message, "edit_date", None) is not None,
        filename=filename,
        pdf_sha256=pdf.sha256,
        excluded=excluded,
        forwarded_from=forwarded_from,
        forwarded_from_url=forwarded_from_url,
    )


async def record_pdf_messages(
    session: AsyncSession, channel: str, *, is_public: bool, found: list[FoundPdf]
) -> str | None:
    """묶음의 메시지·첨부 발견 경로를 저장하고 카드가 없는 원문을 등록한다. 실패하면 사유.

    savepoint 안에서 한다. 여기서 실패해도 같은 트랜잭션의 PDF 행은 커밋된다.
    PDF 행을 먼저 넣은 뒤에 불러야 "이 메시지로 저장한 행" 을 찾는다.
    """
    if not found:
        return None
    try:
        async with session.begin_nested():
            channel_ids = await ensure_channels(session, [
                {"telegram_handle": channel, "name": channel, "is_public": is_public}
            ])
            saved = await save_messages(session, [
                {
                    "channel_id": channel_ids[channel],
                    "msg_id": item.msg_id,
                    "url": f"https://t.me/{channel}/{item.msg_id}",
                    "posted_at": item.posted_at,
                    "author": item.author[:AUTHOR_MAX_CHARS] if item.author else None,
                    "text": item.text,
                    "attachment_name": item.filename,
                    "forwarded_from": item.forwarded_from,
                    "forwarded_from_url": item.forwarded_from_url,
                    "views": item.views,
                    "edited": item.edited,
                    "collected_via": "telethon",
                }
                for item in found
            ])
            links = []
            report_ids = []
            for item, message in zip(found, saved, strict=True):
                report_id, status = (None, "excluded") if item.excluded else (
                    await find_attachment_report(session, channel=channel, msg_id=item.msg_id,
                                                 pdf_sha256=item.pdf_sha256))
                links.append({
                    "message_id": message.id, "kind": "attachment", "position": 1,
                    "discovered_url": None, "final_url": None,
                    "status": status or "not_saved", "error": None, "http_status": None,
                    "fetched_at": None, "news_id": None, "analyst_report_id": report_id,
                })
                if report_id is not None:
                    report_ids.append(report_id)
            await save_message_links(session, links)
            await register_missing_sources(
                session, news_ids=[], report_ids=report_ids, message_ids=[m.id for m in saved],
            )
    except Exception as exc:  # noqa: BLE001 — PDF 행은 지킨다. 실패는 집계해 종료 코드로 알린다
        logger.error("%s: 메시지·발견 경로 저장 실패 (%s)", channel, type(exc).__name__)
        return f"{channel}: 메시지·발견 경로 저장 실패 ({type(exc).__name__})"
    return None


def _is_real_cancel() -> bool:
    """지금 CancelledError 가 우리 작업을 정말로 취소한 것인지.

    텔레그램 연결이 끊기면 Telethon 이 대기 중인 RPC future 를 취소해서
    download_media 안에서 CancelledError 가 올라온다. 그건 이 파일 하나의 실패지
    수집 전체를 멈추라는 뜻이 아니다. 둘을 구분하지 않으면 Ctrl+C 가 안 먹거나
    (전자를 삼키면) 연결이 한 번 끊길 때 200건짜리 수집이 통째로 죽는다(후자).
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _extract(client, message, filename: str, *, attempts: int = 3) -> PdfText:
    """PDF 를 받아 텍스트만 남긴다. 파일은 임시 폴더를 나오면서 사라진다.

    여기가 갖는 건 **내려받기와 재시도**뿐이다. 받아온 바이트를 판정하는 일은
    pdf.py 가 하고 네이버 쪽도 같은 함수를 부른다.

    재시도가 필요한 이유는 텔레그램이라서다. 수백 MB 를 연속으로 받다 보면 연결이
    끊기는데, 한 번 끊겼다고 그 리포트를 버리면 다시 받을 방법이 없다
    (메시지를 처음부터 다시 훑어야 한다). 네이버는 HTTP 라 이 문제가 없다.
    """
    last = "알 수 없음"
    for attempt in range(1, attempts + 1):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                blob = await download_pdf(client, message, Path(tmp))
            # 판정은 pdf.py 가 한다. 네이버 쪽과 같은 함수다 — 받아오는 방법만 다르다.
            # 동기 함수라 별도 스레드에서 돌린다. 안 그러면 이벤트 루프가 멈춘다.
            return await asyncio.to_thread(pdf_text_from_bytes, blob)
        except asyncio.CancelledError:
            if _is_real_cancel():
                raise
            last = "CancelledError: 연결 끊김"
        # 파일 하나가 200건짜리 수집을 죽이면 안 된다. 사유는 body_error 로 남는다.
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
        logger.warning("%s 내려받기 %d/%d 실패: %s", filename, attempt, attempts, last)
        await asyncio.sleep(2 * attempt)  # 끊긴 직후 바로 다시 붙으면 또 끊긴다
    return PdfText(status="failed", error=last)


def public_channels(specs: tuple[str, ...]) -> dict[str, bool]:
    """채널 이름 → 공개 채널인가. channel 표에 처음 등록할 때만 쓴다.

    주소(username)로 연 채널은 공개 채널이다. `이름=채널id:access_hash` 로 연 채널은 공개
    여부를 확인하지 못했으므로 비공개로 적는다. 공개 채널을 비공개로 적는 쪽이 반대보다 안전하다.
    """
    return {parse_channel(spec)[0]: "=" not in spec and ":" not in spec for spec in specs}


async def collect(
    *,
    days: int = 7,
    channels: tuple[str, ...] | None = None,
    limit: int | None = None,
    delay: float = 1.0,
    scope: CollectionScope | None = None,
) -> dict[str, int]:
    """채널별 저장 건수.

    수집 범위(collection_scope.toml 의 telegram_client)는 텔레그램에 접속하기 전에 본다. 허용한
    채널만 열고, 게시일이 기간 밖인 메시지는 받지 않는다. 새 PDF 는 수집량 상한까지만 내려받는다.
    channels 를 주지 않으면 범위의 채널 전부다.
    """
    scope = scope or load_scope()
    source = scope.require("telegram_client")
    channels = channels or tuple(sorted(source.allowed))
    public = public_channels(channels)
    source.check(public)
    since = scope.first_day(datetime.now(KST).date() - timedelta(days=days))
    if since is None:
        raise ScopeError(f"수집 기간({scope.start}~{scope.end}) 밖이다. 받을 메시지가 없다.")

    saved: dict[str, int] = {}
    client = make_client()
    failures: list[str] = []
    try:
        await connect_authorized(client)
        checked_channels = await check_channels(client, channels)
        async with collection_locks(SessionLocal, "telegram_client"), SessionLocal() as session:
            for channel, peer in checked_channels:
                # 채널이 곧 원본 구분이다. 메시지 번호가 채널 안에서만 유일해서
                # 채널로 범위를 좁혀야 비교가 맞는다.
                seen = await known_ids(session, SOURCE, since, channel)
                recorded = await recorded_attachment_ids(session, channel)
                pending_discoveries = seen - recorded
                rows: list[dict] = []
                found: list[FoundPdf] = []  # 이번 묶음에서 PDF 가 붙어 있던 메시지
                n = skipped = stored = 0
                naver_hashes = await known_naver_pdf_hashes(session)
                budget = source.remaining(await count_collected(session, "telegram_client"))
                # 채널 하나가 죽어도 다음 채널은 돌린다. 여기까지 모은 건 아래에서 저장한다.
                try:
                    async for message, filename in iter_pdf_messages(client, peer, since):
                        if not scope.contains(message.date.astimezone(KST).date()):
                            continue  # 기간이 끝난 뒤의 글. 최신부터 훑으므로 기간 안까지 넘긴다
                        if str(message.id) in seen:
                            if str(message.id) not in recorded:
                                # PDF는 이미 있다. 재다운로드 없이 캡션·발견 경로만 복구한다.
                                error = await record_pdf_messages(
                                    session, channel, is_public=public.get(channel, False),
                                    found=[found_pdf(message, filename, PdfText(status="pending"))],
                                )
                                if error:
                                    failures.append(error)
                                else:
                                    recorded.add(str(message.id))
                                    pending_discoveries.discard(str(message.id))
                                await session.commit()
                            continue
                        if limit and n >= limit:
                            if not pending_discoveries:
                                break
                            continue  # 뒤에 있는 기존 PDF의 발견 경로 복구는 계속한다.
                        if n >= budget:
                            if not pending_discoveries:
                                break
                            continue  # 새 PDF만 제한한다. 이미 저장한 PDF의 복구는 상한과 무관하다.

                        pdf = await _extract(client, message, filename)
                        if pdf.status == "failed":
                            failures.append(f"{channel}: PDF 내려받기/추출 실패")
                        if pdf.sha256 and pdf.sha256 in naver_hashes:
                            logger.info("%s: 네이버에 동일 PDF가 있어 건너뛴다", filename)
                            seen.add(str(message.id))
                            skipped += 1
                            # PDF 행은 만들지 않지만 이 메시지에서 발견했다는 기록은 남긴다
                            found.append(found_pdf(message, filename, pdf))
                            await asyncio.sleep(delay)
                            continue
                        # 한국IR협의회가 AI 로 만든 자료는 버린다. 네이버 쪽과 같은 이유다 —
                        # 투자의견·목표주가가 비어 있고 제목이 종목과 맞지 않는다.
                        # 여기서는 본문을 받아본 뒤에야 안다. 네이버처럼 제목의 '[AI] ' 로
                        # 거를 수가 없다 — 재배포 파일명에는 그 표시가 안 남는다.
                        reason = exclusion_reason(filename, pdf.text or "")
                        if reason:
                            logger.info("%s: %s — 건너뛴다", filename, reason)
                            skipped += 1
                            found.append(found_pdf(message, filename, pdf, excluded=True))
                            continue
                        rows.append(
                            to_row(
                                channel=channel,
                                message_id=message.id,
                                filename=filename,
                                posted_at=message.date,
                                pdf=pdf,
                            )
                        )
                        found.append(found_pdf(message, filename, pdf))
                        seen.add(str(message.id))
                        n += 1
                        if len(rows) >= COMMIT_EVERY:
                            stored += await upsert_analyst_reports(session, rows)
                            error = await record_pdf_messages(
                                session, channel, is_public=public.get(channel, False), found=found
                            )
                            if error:
                                failures.append(error)
                            await session.commit()
                            logger.info("%s: %d건 저장", channel, stored)
                            rows, found = [], []
                        await asyncio.sleep(delay)  # 남의 서버다. 내려받기 사이는 쉬어 간다
                except asyncio.CancelledError:
                    if _is_real_cancel():
                        raise
                    failures.append(f"{channel}: 연결 끊김")
                    logger.warning("%s: 연결이 끊겨 %d건에서 멈춘다", channel, n)
                except Exception as exc:  # noqa: BLE001 — 오류는 집계하되 계정 정보는 출력하지 않는다
                    failures.append(f"{channel}: {type(exc).__name__}")
                    logger.error("%s: %d건에서 중단 (%s)", channel, n, type(exc).__name__)

                if rows or found:
                    if rows:
                        stored += await upsert_analyst_reports(session, rows)
                    error = await record_pdf_messages(
                        session, channel, is_public=public.get(channel, False), found=found
                    )
                    if error:
                        failures.append(error)
                    await session.commit()
                saved[channel] = stored
                logger.info("%s: 총 %d건 (수집 대상 외 %d건 제외)", channel, stored, skipped)
    finally:
        await client.disconnect()
    if failures:
        raise RuntimeError(f"일부 수집 실패: {', '.join(sorted(set(failures)))}. "
                           f"완료 저장 {sum(saved.values())}건. 재실행 전에 원인을 확인하세요.")
    return saved


def main() -> None:
    p = argparse.ArgumentParser(description="텔레그램 증권사 리포트 PDF 수집")
    p.add_argument("--days", type=int, default=7, help="오늘로부터 며칠 전까지 (기본 7)")
    p.add_argument(
        "--channel", action="append",
        help=(
            "채널 username, 또는 '이름=채널id:access_hash'. 여러 번 줄 수 있다. "
            "이름은 수집 범위(telegram_client.channels)에 있어야 한다. 기본은 범위의 채널 전부"
        ),
    )
    p.add_argument("--limit", type=int, help="채널당 최대 건수. 시험용")
    p.add_argument("--delay", type=float, default=1.0, help="내려받기 간격(초)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        saved = asyncio.run(
            collect(
                days=args.days,
                channels=tuple(args.channel) if args.channel else None,
                limit=args.limit,
                delay=args.delay,
            )
        )
    except ScopeError as exc:
        p.exit(1, f"{exc}\n")
    except Exception as exc:  # noqa: BLE001 — 오류는 집계하되 계정 정보는 출력하지 않는다
        message = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        p.exit(1, f"텔레그램 수집 실패: {message}\n")
    for channel, n in saved.items():
        print(f"  {channel:16s} {n}건")
    print(f"합계 {sum(saved.values())}건")


if __name__ == "__main__":
    main()
