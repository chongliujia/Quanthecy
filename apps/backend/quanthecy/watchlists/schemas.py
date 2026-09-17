from uuid import UUID

from ninja import Schema
from pydantic import Field

from quanthecy.markets.schemas import MarketSummary


class WatchlistInput(Schema):
    name: str = Field(min_length=1, max_length=80)


class WatchlistOut(Schema):
    id: UUID
    name: str
    count: int


class ItemInput(Schema):
    market_id: UUID


class OrderInput(Schema):
    market_ids: list[UUID] = Field(max_length=100)


class WatchlistMarket(Schema):
    market: MarketSummary
    position: int


class WatchlistDetail(WatchlistOut):
    items: list[WatchlistMarket]
