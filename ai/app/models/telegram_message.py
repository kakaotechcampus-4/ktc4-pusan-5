"""텔레그램 메시지 원문과, 메시지에서 발견한 링크·첨부.

    telegram_messages        한 행 = 채널의 메시지 한 건. (채널, 메시지 번호)가 키다
    telegram_message_links   한 행 = 메시지 안의 링크 하나 또는 첨부 하나 → news / analyst_reports

두 수집기가 같은 표에 넣는다(collected_via).
    web       collectors/news_channels.py. 로그인 없이 t.me/s/ 미리보기를 읽는다
    telethon  collectors/telegram.py. 로그인한 계정으로 PDF 가 붙은 메시지를 읽는다

**본문(text)은 처음 저장한 것을 바꾸지 않는다.** 보고서가 인용한 문장을 원문과 글자로
대조하는데, 나중에 고쳐진 글로 덮으면 이미 쓴 인용이 원문에 없는 문장이 된다. 기준 시각
이후에 고친 내용이 섞이는 것도 막는다. 다시 수집했을 때 글자가 달라졌으면 그 사실만
edit_detected_at 에 남기고, 고친 내용은 저장하지 않는다(repositories/telegram_message.py).

**발견 경로는 메시지마다 따로 남긴다.** 같은 기사가 여러 채널·메시지에 올라와도 news 는
한 행이고, 링크 행은 메시지 수만큼 생긴다. 메시지에 적힌 주소(대개 단축 URL)와 따라가
도착한 주소를 둘 다 둔다.

**운영자가 쓴 글과 남의 자료를 나눠 둔다.** 운영자 허락은 그 채널의 글에만 해당하고, 메시지가
옮겨 온 자료의 발행처에는 해당하지 않는다.
    다른 채널 글을 전달한 메시지   forwarded_from·forwarded_from_url 에 원래 채널·원글을 남긴다.
                                   이 메시지의 원 발행처는 그 채널이다
    메시지에 걸린 외부 기사·PDF    메시지 글이 아니라 news·analyst_reports 의 별도 행이다.
                                   발행처는 언론사·증권사다 (telegram_message_links 로 잇는다)
메시지 글 안에 기사 제목·요약을 옮겨 적은 경우는 글자만으로 가려내지 못한다.

**보관 정책으로 본문을 지운 메시지**는 text 가 NULL 이고 purged_at·purge_reason 이 있다.
행·id·주소는 남고, 다시 수집해도 되살리지 않는다. 빈 문자열(본문 없음)과는 다르다.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text  # 칼럼 이름 text 와 겹치지 않게
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    __table_args__ = (
        # 메시지 번호는 채널 안에서만 유일하다
        UniqueConstraint("channel_id", "msg_id", name="uq_telegram_message_channel_msg"),
        CheckConstraint(
            "collected_via IN ('web', 'telethon')", name="ck_telegram_message_collected_via"
        ),
        Index("ix_telegram_messages_posted_at", "posted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channel.id"))
    msg_id: Mapped[int] = mapped_column(BigInteger)
    url: Mapped[str] = mapped_column(Text)  # https://t.me/<채널>/<번호>. 보고서의 출처 주소
    # 게시 시각. 못 읽었으면 NULL 이다(게시 시각 불명). 수집 시각으로 채우지 않는다.
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author: Mapped[str | None] = mapped_column(String(200))  # 채널 안 서명. 없는 채널이 많다
    # 처음 수집한 본문. 빈 문자열이면 글자 없이 첨부만 올린 메시지다(본문 없음).
    # NULL 이면 보관 정책으로 지운 것이다(purged_at).
    text: Mapped[str | None] = mapped_column(Text)
    attachment_name: Mapped[str | None] = mapped_column(Text)  # 첨부 파일 이름
    # 다른 채널 글을 전달한 메시지면 원래 채널 이름과 원글 주소. 운영자가 쓴 글이면 NULL 이다.
    forwarded_from: Mapped[str | None] = mapped_column(Text)
    forwarded_from_url: Mapped[str | None] = mapped_column(Text)
    # 보이는 주소와 달라서 쓰지 않은 실제 링크(telegram_web/parse.py). 대개 비어 있다.
    hidden_links: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    views: Mapped[str | None] = mapped_column(String(32))  # 마지막으로 본 조회수. "1.2K" 그대로
    # 채널에 '수정됨' 표시가 있었다. 처음 수집하기 전에 고쳤어도 참이다.
    edited: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    # 다시 수집했을 때 본문이 처음 저장한 것과 달랐던 첫 시각. 본문은 바꾸지 않았다.
    edit_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 보관 정책으로 본문을 지운 시각과 사유(repositories/retention.py)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_reason: Mapped[str | None] = mapped_column(Text)
    collected_via: Mapped[str] = mapped_column(String(16))  # web | telethon
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TelegramMessageLink(Base):
    """메시지에서 발견한 것 하나.

    kind = url         메시지 본문의 링크. position 은 메시지 안 순서(1부터)다
        status  열었으면 news_link 의 LinkStatus 그대로
                    ok · no_body · pdf · not_html · too_large · http_error · blocked · error
                열지 않았으면 그 이유
                    stale          게시 24시간이 지났거나 게시 시각을 몰라서 (기준 시각 규칙)
                    over_limit     메시지당 여는 링크 수 상한을 넘어서
                    not_fetchable  주소가 아니라 티커 문자열("PLTR.US")이라서
                    not_opened     링크를 열지 않는 설정(--no-links)으로 수집해서
                    out_of_scope   수집 범위 밖이라서 (telegram_link 가 꺼졌거나 수집량 상한)
    kind = attachment  메시지에 붙은 PDF. position 은 1 이다
        status  saved      이 메시지의 PDF 를 analyst_reports 에 저장했다
                duplicate  네이버에 같은 PDF 가 있어 그 행에 연결했다
                excluded   수집 대상이 아니어서(AI 생성 자료 등) 저장하지 않았다
                not_saved  이 메시지로 저장한 행도, 같은 네이버 PDF 도 찾지 못했다
    """

    __tablename__ = "telegram_message_links"
    __table_args__ = (
        UniqueConstraint("message_id", "kind", "position", name="uq_telegram_message_link_position"),
        CheckConstraint("kind IN ('url', 'attachment')", name="ck_telegram_message_link_kind"),
        # 링크는 적힌 주소가 있고 첨부는 없다
        CheckConstraint(
            "(kind = 'url') = (discovered_url IS NOT NULL)", name="ck_telegram_message_link_url"
        ),
        # 하나의 발견은 기사 하나 또는 PDF 하나로만 이어진다
        CheckConstraint(
            "num_nonnulls(news_id, analyst_report_id) <= 1", name="ck_telegram_message_link_target"
        ),
        Index("ix_telegram_message_links_news_id", "news_id"),
        Index("ix_telegram_message_links_analyst_report_id", "analyst_report_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_messages.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer)
    discovered_url: Mapped[str | None] = mapped_column(Text)  # 메시지에 적힌 주소 그대로
    final_url: Mapped[str | None] = mapped_column(Text)  # 리다이렉트를 따라 도착한 주소
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 링크를 연 시각
    news_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("news.id"))
    analyst_report_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("analyst_reports.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
