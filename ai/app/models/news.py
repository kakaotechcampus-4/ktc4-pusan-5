"""뉴스 기사 원문. 한 행 = 기사 한 건(정규화한 주소 기준).

**backend 가 만든 표를 AI 가 넘겨받았다.** 표 자체는 backend 첫 리비전(99dbfe02fd98)이
만들었고, 그 뒤의 구조 변경은 ai/alembic(0020~)이 한다. backend 는 이 표를 비교하지 않는다.
기존 행과 id 는 그대로다.

두 경로로 들어온다(source).
    naver     네이버 뉴스 검색. 발행 시각·요약을 API 가 준다. 본문은 trafilatura 로 뽑는다
    telegram  텔레그램 메시지에 걸린 링크를 따라가 연 기사. 본문은 news_link(bs4)로 뽑는다.
              발행 시각을 모른다 — 수집 시각으로 채우지 않고 NULL 로 둔다

같은 기사가 두 경로로 들어와도 한 행이다. canonical_url(services/news/url.py)로 가른다.
url 은 처음 들어온 주소 그대로다. 어느 메시지에서 어떤 주소로 발견했는지는 행이 아니라
telegram_message_links 에 남는다.

**본문은 한 번 확보하면 바꾸지 않는다.** 기사는 발행 뒤에도 고쳐지는데, 보고서는 기준 시각
이전의 정보만 써야 한다. 나중에 다시 열어 받은 본문으로 덮으면 이미 쓴 인용과 원문이 어긋나고
기준 시각 이후의 수정이 섞인다. 실패했던 본문만 다음 수집에서 채운다(repositories/news.py).

**본문을 무기한 두지는 않는다.** 보관 정책으로 지운 기사는 body_status = purged 이고 본문이
비어 있다. 행과 id 는 남아 공통 자료 ID·인용이 깨지지 않고, 다시 수집해도 되살리지 않는다.

cleaned_text 는 기사 본문 **전체**다. 앞 3문장 발췌(LinkBody.excerpt)를
여기 넣지 않는다 — 발췌는 본문에서 언제든 다시 뽑을 수 있지만 그 반대는 안 된다.
네이버 경로는 backend 때처럼 3,000자에서 자른 값이다(clean.MAX_CHARS).
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 본문 상태. 기사 하나에 대한 최종 상태라 원인은 body_error 에 따로 둔다.
#   ok      본문이 있다
#   failed  열었지만 본문을 못 얻었다 (HTTP 오류·추출 실패·본문 없음 등)
#   purged  보관 정책으로 본문을 지웠다. 다시 수집해도 되살리지 않는다 (purged_at·purge_reason)
BODY_STATUSES = ("ok", "failed", "purged")


class News(Base):
    __tablename__ = "news"
    __table_args__ = (
        # 정규화한 주소가 같으면 같은 기사다. NULL 은 여러 개일 수 있다 — 이관 전 행은
        # 등록 처리(collectors/sources.py)가 채우기 전까지 비어 있다.
        UniqueConstraint("canonical_url", name="uq_news_canonical_url"),
        CheckConstraint("body_status IN ('ok', 'failed', 'purged')", name="ck_news_body_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 처음 들어온 원문 주소. 네이버는 originallink, 텔레그램은 리다이렉트를 따라간 최종 주소다.
    url: Mapped[str] = mapped_column(Text, unique=True)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)  # 못 읽었으면 빈 문자열. 다음 수집에서 채운다
    publisher: Mapped[str] = mapped_column(String(100))  # 원 발행처. 지금은 원문 도메인
    source: Mapped[str] = mapped_column(String(20))  # 처음 들어온 경로: naver | telegram
    # 발행 시각. 모르면 NULL 이다. 수집 시각·메시지 게시 시각으로 대신 채우지 않는다.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")  # 네이버가 준 요약. 본문 아님
    cleaned_text: Mapped[str | None] = mapped_column(Text)  # 정제한 본문 전체

    body_status: Mapped[str] = mapped_column(String(16))
    # 실패 사유. 네이버는 http_404·extract_empty, 텔레그램은 LinkStatus(no_body·http_error...)
    # 를 앞에 붙인다. 이관 전 행은 사유가 기록되지 않아 unrecorded 다.
    body_error: Mapped[str | None] = mapped_column(Text)
    # 본문을 받으러 마지막으로 연 시각. ok 면 그 본문을 받은 시각이다. 기준 시각보다 늦게
    # 받은 본문을 걸러낼 때 쓴다. 이관 전 행은 collected_at(상한값)으로 채웠다.
    body_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body_extractor: Mapped[str | None] = mapped_column(String(32))  # trafilatura | news_link
    # 보관 정책으로 본문을 지운 시각과 사유(repositories/retention.py). 행·id·출처 정보는 남긴다.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_reason: Mapped[str | None] = mapped_column(Text)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
