"""종목 변동 요인 보고서 조회. 표는 ai 프로젝트의 Alembic 이 만들고 backend 는 읽기만 한다.

backend 의 `Base` 에 모델을 넣으면 `alembic revision --autogenerate` 가 이 표를 만들려는 마이그레이션을
뽑아 ai 쪽 이력과 충돌한다. 그래서 MetaData 에 묶이지 않는 `table()` 로 읽을 칼럼만 적는다.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, column, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

TABLE_NAME = "stock_move_analyses"

analyses = table(
    TABLE_NAME,
    column("id", BigInteger),
    column("ticker", String),
    column("name", String),
    column("target_date", Date),
    column("as_of", DateTime(timezone=True)),
    column("change_pct", Numeric),
    column("generated_at", DateTime(timezone=True)),
    column("loaded_at", DateTime(timezone=True)),
    column("raw_json", JSONB),
    column("verify_status", String),
    column("parse_status", String),
)


class ReportStoreUnavailable(Exception):
    """보고서 표를 읽을 수 없다. ai 마이그레이션이 아직 적용되지 않은 서버가 대표적이다."""


@dataclass(frozen=True)
class ReportRow:
    id: int
    ticker: str
    name: str | None
    target_date: date | None
    as_of: datetime | None
    change_pct: Any
    generated_at: datetime | None
    loaded_at: datetime
    raw_json: Any


def latest_passed_statement(code: str):
    """근거 검증을 통과했고 파싱이 정상인 행 중 가장 최근 것 하나.

    같은 종목·기준 시각을 다시 생성하면 새 행으로 쌓이므로(INSERT only) 날짜·기준 시각·id 순으로 고른다.
    """
    return (
        select(*analyses.c)
        .where(
            analyses.c.ticker == code,
            analyses.c.verify_status == "passed",
            analyses.c.parse_status == "ok",
        )
        .order_by(
            analyses.c.target_date.desc().nulls_last(),
            analyses.c.as_of.desc().nulls_last(),
            analyses.c.id.desc(),
        )
        .limit(1)
    )


def is_missing_table(exc: DBAPIError) -> bool:
    orig = str(getattr(exc, "orig", exc))
    return TABLE_NAME in orig and "does not exist" in orig


class StockReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_passed(self, code: str) -> ReportRow | None:
        try:
            row = (await self.session.execute(latest_passed_statement(code))).one_or_none()
        except DBAPIError as exc:
            if is_missing_table(exc):
                raise ReportStoreUnavailable(TABLE_NAME) from exc
            raise
        if row is None:
            return None
        return ReportRow(
            id=row.id,
            ticker=row.ticker,
            name=row.name,
            target_date=row.target_date,
            as_of=row.as_of,
            change_pct=row.change_pct,
            generated_at=row.generated_at,
            loaded_at=row.loaded_at,
            raw_json=row.raw_json,
        )
