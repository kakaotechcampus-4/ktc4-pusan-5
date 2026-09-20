from datetime import date, datetime
from typing import Literal

from pydantic import Field, FiniteFloat

from app.schemas.base import CamelModel

FLOW_KINDS = ("flowBuy", "flowSell")
SECTOR_KINDS = ("sectorKospi", "sectorKosdaq")


class FlowItem(CamelModel):
    code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    name: str = Field(min_length=1)
    net_volume: int = Field(ge=-9007199254740991, le=9007199254740991)


class SectorItem(CamelModel):
    name: str = Field(min_length=1)
    change: FiniteFloat
    as_of: date


class FlowBoard(CamelModel):
    kind: Literal["flowBuy", "flowSell"]
    status: Literal["ready", "stale", "empty", "pending", "unavailable"]
    source: str = "KIS"
    collected_at: datetime | None = None
    items: list[FlowItem] = Field(default_factory=list)


class SectorBoard(CamelModel):
    kind: Literal["sectorKospi", "sectorKosdaq"]
    status: Literal["ready", "stale", "empty", "pending", "unavailable"]
    source: str = "KRX"
    collected_at: datetime | None = None
    items: list[SectorItem] = Field(default_factory=list)
