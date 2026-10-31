"""보관 정책에 따른 본문 삭제. 본문만 지우고 행·id·출처 정보는 남긴다.

언제 무엇을 지울지(보관 기간·대상·처리 담당)는 아직 정하지 않았다.
여기는 정해진 뒤 실행할 방법만 둔다. 자동으로 돌지 않고 사람이 명령으로 실행한다
(`python -m app.collectors.sources purge`).

    지우는 것      news.cleaned_text · analyst_reports.body_text · telegram_messages.text
    남기는 것      행과 id, 제목·주소·발행처·시각, PDF 해시, 공통 자료 ID 카드, 발견 경로.
                   공통 ID 와 인용(report_citation)이 가리키는 행이 사라지지 않게 하려는 것이다
    따로 남는 사본  요약(news.summary·analyst_reports.summary_text), 분류 근거·생성 입력,
                   JSONL 파일, 로그·백업. 사본의 삭제 범위는 분류·생성 담당과 맞춘 뒤 정한다

지운 행은 purged 로 표시하고 지운 시각·사유를 남긴다. 다시 수집해도 되살리지 않는다
(repositories/news.py·telegram_message.py·analyst_report.py). 원문이 없으므로 재분류나 과거 결과
검증은 할 수 없고, 조회(get_sources)는 본문 대신 그 사유를 돌려준다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalystReport, News, SourceCard, TelegramMessage

KINDS = ("news", "pdf", "message")


@dataclass
class PurgeTargets:
    """지울 원문 행 id. 이미 지운 행은 들어 있지 않다."""

    news: list[int] = field(default_factory=list)
    pdf: list[int] = field(default_factory=list)
    message: list[int] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"news": len(self.news), "pdf": len(self.pdf), "message": len(self.message)}


async def _ids(session: AsyncSession, query) -> list[int]:
    return list((await session.execute(query)).scalars().all())


async def purge_targets(
    session: AsyncSession,
    *,
    card_ids: list[int] | None = None,
    kind: str | None = None,
    collected_before: datetime | None = None,
) -> PurgeTargets:
    """공통 자료 ID 들, 또는 종류와 수집 시각 기준으로 지울 행을 고른다. 아직 지우지 않는다."""
    if (card_ids is None) == (kind is None):
        raise ValueError("card_ids 또는 kind(+collected_before) 중 하나로 고른다")
    if card_ids is not None:
        cards = (await session.execute(
            select(SourceCard.news_id, SourceCard.analyst_report_id, SourceCard.telegram_message_id)
            .where(SourceCard.id.in_(card_ids))
        )).all()
        news_ids = [n for n, _r, _m in cards if n is not None]
        report_ids = [r for _n, r, _m in cards if r is not None]
        message_ids = [m for _n, _r, m in cards if m is not None]
        return PurgeTargets(
            news=await _ids(session, select(News.id).where(
                News.id.in_(news_ids), News.body_status != "purged")),
            pdf=await _ids(session, select(AnalystReport.id).where(
                AnalystReport.id.in_(report_ids), AnalystReport.body_status != "purged")),
            message=await _ids(session, select(TelegramMessage.id).where(
                TelegramMessage.id.in_(message_ids), TelegramMessage.purged_at.is_(None))),
        )

    if kind not in KINDS or collected_before is None:
        raise ValueError(f"kind 는 {' | '.join(KINDS)} 중 하나이고 collected_before 가 필요하다")
    targets = PurgeTargets()
    if kind == "news":
        targets.news = await _ids(session, select(News.id).where(
            News.collected_at < collected_before, News.body_status != "purged"))
    elif kind == "pdf":
        targets.pdf = await _ids(session, select(AnalystReport.id).where(
            AnalystReport.collected_at < collected_before, AnalystReport.body_status != "purged"))
    else:
        targets.message = await _ids(session, select(TelegramMessage.id).where(
            TelegramMessage.collected_at < collected_before, TelegramMessage.purged_at.is_(None)))
    return targets


async def purge(session: AsyncSession, targets: PurgeTargets, *, reason: str) -> dict[str, int]:
    """고른 행의 본문을 지운다. 종류별로 지운 수. 커밋은 부르는 쪽이 한다."""
    if not reason.strip():
        raise ValueError("지우는 사유를 적는다 (어느 보관 정책에 따른 것인지)")
    now = func.now()
    news = await _ids(session, update(News)
                      .where(News.id.in_(targets.news), News.body_status != "purged")
                      .values(cleaned_text=None, body_status="purged", purged_at=now,
                              purge_reason=reason)
                      .returning(News.id))
    pdf = await _ids(session, update(AnalystReport)
                     .where(AnalystReport.id.in_(targets.pdf),
                            AnalystReport.body_status != "purged")
                     .values(body_text=None, body_status="purged", purged_at=now,
                             purge_reason=reason)
                     .returning(AnalystReport.id))
    message = await _ids(session, update(TelegramMessage)
                         .where(TelegramMessage.id.in_(targets.message),
                                TelegramMessage.purged_at.is_(None))
                         .values(text=None, purged_at=now, purge_reason=reason)
                         .returning(TelegramMessage.id))
    return {"news": len(news), "pdf": len(pdf), "message": len(message)}
