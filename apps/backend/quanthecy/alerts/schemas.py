from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field

Kind = Literal["PROBABILITY_MOVE", "SPREAD_WIDENING"]
Direction = Literal["EITHER", "UP", "DOWN"]


class RuleInput(Schema):
    name: str = Field(min_length=1, max_length=100)
    kind: Kind
    direction: Direction = "EITHER"
    threshold_pp: Decimal = Field(gt=0, le=100, max_digits=5, decimal_places=2)
    window_minutes: Literal[5, 15, 60] = 15
    cooldown_minutes: int = Field(ge=1, le=1440, default=30)
    enabled: bool = True


class RuleState(Schema):
    market_id: UUID
    title: str
    status: str
    reason: str
    value_pp: float | None
    evaluated_at: datetime | None


class RuleOut(RuleInput):
    id: UUID
    watchlist_id: UUID
    revision: int
    states: list[RuleState]


class EventOut(Schema):
    id: UUID
    market_id: UUID
    title: str
    platform: str
    rule_name: str
    kind: Kind
    direction: Direction
    threshold_pp: float
    window_minutes: int
    value_pp: float
    revision: int
    observed_at: datetime
    created_at: datetime
    is_read: bool


class EventPage(Schema):
    items: list[EventOut]
    total: int
    unread: int
    offset: int
    limit: int


class EventDetail(EventOut):
    snapshot: dict[str, Any]


class ReadInput(Schema):
    read: bool = True
