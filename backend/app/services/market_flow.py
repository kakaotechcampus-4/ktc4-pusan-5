from datetime import UTC, datetime

from app.schemas.market_flow import FLOW_KINDS, SECTOR_KINDS, FlowBoard, FlowItem, SectorBoard
from app.services.market_data import MarketDataError
from app.services.ranking import integer


def parse_flow(rows: list[dict], kind: str) -> list[FlowItem]:
    if not isinstance(rows, list) or len(rows) > 100:
        raise MarketDataError("INVALID_RESPONSE")
    items = [
        FlowItem(
            code=r["mksc_shrn_iscd"], name=r["hts_kor_isnm"], net_volume=integer(r["ntby_qty"])
        )
        for r in rows
    ]
    values = [item.net_volume for item in items]
    if len({item.code for item in items}) != len(items) or values != sorted(
        values, reverse=kind == "flowBuy"
    ):
        raise MarketDataError("INVALID_RANK_ORDER")
    return [
        item
        for item in items
        if (item.net_volume > 0 if kind == "flowBuy" else item.net_volume < 0)
    ]


def market_flow_boards(snapshots):
    def board(kind, model, interval):
        row = snapshots.get(kind)
        status = "pending"
        if row and row.items is not None:
            stale = (
                row.error_code
                or not row.collected_at
                or (datetime.now(UTC) - row.collected_at).total_seconds() > interval * 3
            )
            status = "stale" if stale else "ready" if row.items else "empty"
        elif row and row.error_code:
            status = "unavailable"
        return model(
            kind=kind,
            status=status,
            collected_at=row.collected_at if row else None,
            items=row.items[:5] if row and row.items else [],
        )

    return (
        [board(k, FlowBoard, 60) for k in FLOW_KINDS],
        [board(k, SectorBoard, 3600) for k in SECTOR_KINDS],
    )
