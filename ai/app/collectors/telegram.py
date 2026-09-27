"""텔레그램 채널의 증권사 리포트 PDF 수집 → 정규화 → DB 저장.

    uv run python -m app.collectors.telegram --days 7
    uv run python -m app.collectors.telegram --days 1 --channel sunstudy1234 --limit 5

네이버 컬렉터(app/collectors/analyst_report.py)와 같은 analyst_reports 테이블에 넣는다.
`source` 로만 갈린다. 테이블·upsert·PDF 추출은 전부 재사용한다.

네이버와 다른 점은 네트워크 비용이다. 네이버는 PDF 가 건당 수백 KB 인데 텔레그램은
평균 3.7MB 다(선진짱 220건 806MB). 그래서 이미 받은 건 반드시 건너뛴다.
"""

import argparse
import asyncio
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from app.core.database import SessionLocal
from app.repositories.analyst_report import (
    known_ids,
    known_naver_pdf_hashes,
    upsert_analyst_reports,
)
from app.services.analyst.pdf import pdf_text_from_bytes
from app.services.analyst.schema import PdfText
from app.services.analyst.telegram import (
    DEFAULT_CHANNELS,
    KST,
    check_channels,
    connect_authorized,
    download_pdf,
    exclusion_reason,
    iter_pdf_messages,
    make_client,
    to_row,
)

logger = logging.getLogger(__name__)
SOURCE = "telegram"
COMMIT_EVERY = 20  # 200건짜리 채널에서 중간에 끊겨도 앞은 남게


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


async def collect(
    *,
    days: int = 7,
    channels: tuple[str, ...] = DEFAULT_CHANNELS,
    limit: int | None = None,
    delay: float = 1.0,
) -> dict[str, int]:
    """채널별 저장 건수."""
    since = datetime.now(KST).date() - timedelta(days=days)

    saved: dict[str, int] = {}
    client = make_client()
    failures: list[str] = []
    try:
        await connect_authorized(client)
        checked_channels = await check_channels(client, channels)
        async with SessionLocal() as session:
            for channel, peer in checked_channels:
                # 채널이 곧 원본 구분이다. 메시지 번호가 채널 안에서만 유일해서
                # 채널로 범위를 좁혀야 비교가 맞는다.
                seen = await known_ids(session, SOURCE, since, channel)
                rows: list[dict] = []
                n = skipped = stored = 0
                naver_hashes = await known_naver_pdf_hashes(session)
                # 채널 하나가 죽어도 다음 채널은 돌린다. 여기까지 모은 건 아래에서 저장한다.
                try:
                    async for message, filename in iter_pdf_messages(client, peer, since):
                        if str(message.id) in seen:
                            continue
                        if limit and n >= limit:
                            break

                        pdf = await _extract(client, message, filename)
                        if pdf.status == "failed":
                            failures.append(f"{channel}: PDF 내려받기/추출 실패")
                        if pdf.sha256 and pdf.sha256 in naver_hashes:
                            logger.info("%s: 네이버에 동일 PDF가 있어 건너뛴다", filename)
                            seen.add(str(message.id))
                            skipped += 1
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
                        seen.add(str(message.id))
                        n += 1
                        if len(rows) >= COMMIT_EVERY:
                            stored += await upsert_analyst_reports(session, rows)
                            await session.commit()
                            logger.info("%s: %d건 저장", channel, stored)
                            rows = []
                        await asyncio.sleep(delay)  # 남의 서버다. 내려받기 사이는 쉬어 간다
                except asyncio.CancelledError:
                    if _is_real_cancel():
                        raise
                    failures.append(f"{channel}: 연결 끊김")
                    logger.warning("%s: 연결이 끊겨 %d건에서 멈춘다", channel, n)
                except Exception as exc:  # noqa: BLE001 — 오류는 집계하되 계정 정보는 출력하지 않는다
                    failures.append(f"{channel}: {type(exc).__name__}")
                    logger.error("%s: %d건에서 중단 (%s)", channel, n, type(exc).__name__)

                if rows:
                    stored += await upsert_analyst_reports(session, rows)
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
            f"기본 {', '.join(DEFAULT_CHANNELS)}"
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
                channels=tuple(args.channel) if args.channel else DEFAULT_CHANNELS,
                limit=args.limit,
                delay=args.delay,
            )
        )
    except Exception as exc:  # noqa: BLE001 — 오류는 집계하되 계정 정보는 출력하지 않는다
        message = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        p.exit(1, f"텔레그램 수집 실패: {message}\n")
    for channel, n in saved.items():
        print(f"  {channel:16s} {n}건")
    print(f"합계 {sum(saved.values())}건")


if __name__ == "__main__":
    main()
