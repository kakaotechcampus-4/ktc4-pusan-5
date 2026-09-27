from datetime import UTC, datetime

from app.models.ranking import RankingSnapshot
from app.schemas.ranking import ACTIVE_RANKINGS, RANKING_KINDS, RankingBoard, RankingItem
from app.services.market_data import MarketDataError, number


def integer(raw: object) -> int:
    value = number(raw)
    if value != value.to_integral_value():
        raise MarketDataError("INVALID_RESPONSE")
    return int(value)


def parse_ranking(rows: list[dict], kind: str = "tradingValue") -> list[RankingItem]:
    if not isinstance(rows, list) or len(rows) > 100:
        raise MarketDataError("INVALID_RESPONSE")
    items = []
    for row in rows:
        items.append(
            RankingItem(
                rank=integer(row["data_rank"]),
                code=row["stck_shrn_iscd" if kind in ("gainers", "losers") else "mksc_shrn_iscd"],
                name=row["hts_kor_isnm"],
                price=integer(row["stck_prpr"]),
                change=float(number(row["prdy_ctrt"])),
                volume=integer(row["acml_vol"]),
                trading_value=None
                if kind in ("gainers", "losers")
                else integer(row["acml_tr_pbmn"]),
            )
        )
    if len({item.code for item in items}) != len(items) or len(
        {item.rank for item in items}
    ) != len(items):
        raise MarketDataError("INVALID_RESPONSE")
    items.sort(key=lambda item: item.rank)
    if kind in ("gainers", "losers"):
        rates = [item.change for item in items]
        if rates != sorted(rates, reverse=kind == "gainers"):
            raise MarketDataError("INVALID_RANK_ORDER")
        # 거래 종목이 적으면 반대 방향/보합 종목까지 반환될 수 있다.
        items = [
            item for item in items if (item.change > 0 if kind == "gainers" else item.change < 0)
        ]
    return items


def ranking_boards(snapshots: dict[str, RankingSnapshot]) -> list[RankingBoard]:
    boards = []
    now = datetime.now(UTC)
    for kind in RANKING_KINDS:
        row = snapshots.get(kind) if kind in ACTIVE_RANKINGS else None
        status = "pending" if kind in ACTIVE_RANKINGS else "notConfigured"
        if row and row.items is not None:
            stale = (
                row.error_code
                or not row.collected_at
                or (now - row.collected_at).total_seconds() > 180
            )
            status = "stale" if stale else "ready" if row.items else "empty"
        elif row and row.error_code:
            status = "unavailable"
        boards.append(
            RankingBoard(
                kind=kind,
                status=status,
                collected_at=row.collected_at if row else None,
                items=[RankingItem.model_validate(item) for item in row.items[:10]]
                if row and row.items
                else [],
            )
        )
    return boards
