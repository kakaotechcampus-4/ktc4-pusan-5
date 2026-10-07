"""텔레그램 채널·메시지·발견 링크 읽기·쓰기.

    ensure_channels      처음 보는 채널만 channel 에 넣는다. 있는 행은 건드리지 않는다
    save_messages        (채널, 메시지 번호)마다 한 행. 다시 수집해도 행이 늘지 않는다
    save_message_links   (메시지, 종류, 순서)마다 한 행. 실패했던 링크만 이번 결과로 바꾼다

메시지 본문은 처음 저장한 것을 바꾸지 않는다(models/telegram_message.py). 다시 수집했을 때
글자가 달라졌으면 edit_detected_at 만 남긴다. 그 메시지의 링크도 처음 것을 기준으로 두므로,
부르는 쪽은 text_changed 인 메시지의 링크를 다시 저장하지 않는다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalystReport, Channel, TelegramMessage, TelegramMessageLink

# 링크를 열지 않은 이유. 이전에 열어 둔 결과를 이 값으로 덮지 않는다.
NOT_OPENED = frozenset({"stale", "over_limit", "not_fetchable", "not_opened", "out_of_scope"})
# 더 나아질 게 없는 결과. 다시 수집해도 바꾸지 않는다.
SETTLED = frozenset({"ok", "saved", "duplicate"})
# 링크 행에서 다시 수집할 때 바뀔 수 있는 칼럼
LINK_RESULT_FIELDS = (
    "final_url", "status", "error", "http_status", "fetched_at", "news_id", "analyst_report_id",
)


@dataclass
class SavedMessage:
    id: int
    inserted: bool  # 이번에 처음 저장했다
    text_changed: bool  # 처음 저장한 본문과 글자가 달랐다 (수정 감지)


async def ensure_channels(session: AsyncSession, channels: list[dict]) -> dict[str, int]:
    """telegram_handle → channel.id. 행 키는 telegram_handle·name·is_public 이다.

    이미 있는 채널은 이름·공개 여부까지 그대로 둔다. 등급·검수는 사람이 채우는 값이다.
    """
    if not channels:
        return {}
    now = datetime.now(UTC)
    unique = list({c["telegram_handle"]: c for c in channels}.values())
    await session.execute(
        insert(Channel)
        .values([{**c, "created_at": now} for c in unique])
        .on_conflict_do_nothing(index_elements=["telegram_handle"])
    )
    rows = await session.execute(
        select(Channel.telegram_handle, Channel.id).where(
            Channel.telegram_handle.in_([c["telegram_handle"] for c in unique])
        )
    )
    return {handle: channel_id for handle, channel_id in rows.all()}


def _refresh(message: TelegramMessage, row: dict) -> bool:
    """이미 있는 메시지를 이번 관찰로 갱신한다. 본문이 달라졌으면 True.

    보관 정책으로 본문을 지운 메시지(purged_at)는 본문을 비교하지도 되살리지도 않는다.
    """
    changed = message.purged_at is None and message.text != row["text"]
    if changed and message.edit_detected_at is None:
        message.edit_detected_at = func.now()
    message.edited = message.edited or bool(row.get("edited"))
    message.last_seen_at = func.now()
    if row.get("views") is not None:
        message.views = row["views"]
    # 처음에 못 읽은 값만 채운다. 본문·링크 서식은 처음 것을 둔다.
    for name in ("posted_at", "author", "attachment_name", "forwarded_from", "forwarded_from_url"):
        if getattr(message, name) is None and row.get(name) is not None:
            setattr(message, name, row[name])
    return changed


async def save_messages(session: AsyncSession, rows: list[dict]) -> list[SavedMessage]:
    """메시지 행을 넣거나 갱신한다. 결과는 넘긴 순서대로다. 커밋은 부르는 쪽이 한다."""
    saved: list[SavedMessage] = []
    for row in rows:
        new_id = (
            await session.execute(
                insert(TelegramMessage)
                .values(**row)
                .on_conflict_do_nothing(constraint="uq_telegram_message_channel_msg")
                .returning(TelegramMessage.id)
            )
        ).scalar_one_or_none()
        if new_id is not None:
            saved.append(SavedMessage(id=new_id, inserted=True, text_changed=False))
            continue
        message = (
            await session.execute(
                select(TelegramMessage)
                .where(
                    TelegramMessage.channel_id == row["channel_id"],
                    TelegramMessage.msg_id == row["msg_id"],
                )
                .with_for_update()
            )
        ).scalar_one()
        changed = _refresh(message, row)
        await session.flush()
        saved.append(SavedMessage(id=message.id, inserted=False, text_changed=changed))
    return saved


async def known_message_keys(
    session: AsyncSession, keys: list[tuple[str, int]]
) -> set[tuple[str, int]]:
    """(채널, 메시지 번호) 중 이미 저장된 것. 수집량 상한을 셀 때 새 메시지만 세려고 쓴다."""
    channels = {channel for channel, _msg_id in keys}
    if not channels:
        return set()
    rows = await session.execute(
        select(Channel.telegram_handle, TelegramMessage.msg_id)
        .join(TelegramMessage, TelegramMessage.channel_id == Channel.id)
        .where(Channel.telegram_handle.in_(channels),
               TelegramMessage.msg_id.in_({msg_id for _channel, msg_id in keys}))
    )
    return {(handle, msg_id) for handle, msg_id in rows.all()} & set(keys)


def _should_replace(existing_status: str, new_status: str) -> bool:
    """이미 있는 링크 결과를 이번 결과로 바꿀지."""
    return existing_status not in SETTLED and new_status not in NOT_OPENED


async def save_message_links(session: AsyncSession, rows: list[dict]) -> tuple[int, int]:
    """(새로 넣은 수, 결과를 바꾼 수). 커밋은 부르는 쪽이 한다.

    성공한 결과는 다시 열어 실패해도 그대로 둔다. "열지 않음"(stale 등)은 이전 결과를 덮지
    않는다. 다음 날 수집하면 어제 메시지는 24시간이 지나 stale 이 되는데, 그걸로 어제 연
    결과를 지우면 안 된다.
    """
    inserted = replaced = 0
    for row in rows:
        new_id = (
            await session.execute(
                insert(TelegramMessageLink)
                .values(**row)
                .on_conflict_do_nothing(constraint="uq_telegram_message_link_position")
                .returning(TelegramMessageLink.id)
            )
        ).scalar_one_or_none()
        if new_id is not None:
            inserted += 1
            continue
        link = (
            await session.execute(
                select(TelegramMessageLink)
                .where(
                    TelegramMessageLink.message_id == row["message_id"],
                    TelegramMessageLink.kind == row["kind"],
                    TelegramMessageLink.position == row["position"],
                )
                .with_for_update()
            )
        ).scalar_one()
        if not _should_replace(link.status, row["status"]):
            continue
        for name in LINK_RESULT_FIELDS:
            setattr(link, name, row.get(name))
        replaced += 1
    await session.flush()
    return inserted, replaced


async def find_attachment_report(
    session: AsyncSession, *, channel: str, msg_id: int, pdf_sha256: str | None
) -> tuple[int | None, str | None]:
    """메시지에 붙은 PDF 가 저장된 analyst_reports 행과 그 연결 상태.

    이 메시지로 저장한 텔레그램 행이 있으면 (id, "saved"), 네이버에 같은 PDF 가 있어 건너뛴
    것이면 그 네이버 행의 (id, "duplicate"), 둘 다 없으면 (None, None) 이다.
    """
    own = (
        await session.execute(
            select(AnalystReport.id).where(
                AnalystReport.source == "telegram",
                AnalystReport.source_category == channel,
                AnalystReport.source_id == str(msg_id),
            )
        )
    ).scalar_one_or_none()
    if own is not None:
        return own, "saved"
    if pdf_sha256:
        naver = (
            await session.execute(
                select(AnalystReport.id)
                .where(AnalystReport.source == "naver", AnalystReport.pdf_sha256 == pdf_sha256)
                .order_by(AnalystReport.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if naver is not None:
            return naver, "duplicate"
    return None, None
