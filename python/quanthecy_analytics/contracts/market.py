"""Authoring source for the shared, versioned JSON wire contract."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def valid_timestamp(value: str) -> str:
    datetime.fromisoformat(value)
    return value


UtcTime = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"),
    Field(json_schema_extra={"format": "date-time"}),
    AfterValidator(valid_timestamp),
]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=255)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Event(ContractModel):
    id: UUID
    exchange_id: Identifier
    title: Annotated[str, Field(min_length=1)]


class Market(ContractModel):
    id: UUID
    exchange_id: Identifier
    title: Annotated[str, Field(min_length=1)]
    description: str
    status: Literal["OPEN", "CLOSED", "RESOLVED", "CANCELLED", "UNKNOWN"]
    rules_version: Identifier
    resolution_rules: str
    resolution_source: str | None
    opens_at: UtcTime | None
    closes_at: UtcTime | None
    resolved_at: UtcTime | None


class Outcome(ContractModel):
    id: UUID
    exchange_id: Identifier
    label: Annotated[str, Field(min_length=1)]
    result: Literal["WON", "LOST", "VOID", "UNKNOWN"]


class ProbabilityValue(ContractModel):
    value: Probability
    basis: Literal["LAST_TRADE", "MIDPOINT", "BEST_BID", "BEST_ASK"]
    source: Identifier
    as_of: UtcTime


class ActivityValue(ContractModel):
    value: NonNegative
    unit: Literal["USD", "CONTRACTS"]
    basis: Identifier
    window_start: UtcTime | None
    as_of: UtcTime


class Provenance(ContractModel):
    transport: Literal["REST", "WEBSOCKET", "BACKFILL"]
    source: Identifier
    source_event_id: Identifier | None
    sequence: Identifier | None
    payload_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class MarketObservation(ContractModel):
    schema_version: Literal["1.0.0"]
    observation_id: UUID
    platform: Literal["polymarket", "kalshi"]
    event: Event
    market: Market
    outcome: Outcome
    event_at: UtcTime | None
    received_at: UtcTime
    recorded_at: UtcTime
    probability: ProbabilityValue | None
    best_bid: Probability | None
    best_ask: Probability | None
    volume: ActivityValue | None
    liquidity: ActivityValue | None
    quality_flags: list[
        Literal[
            "STALE",
            "GAP",
            "OUT_OF_ORDER",
            "SOURCE_TIME_MISSING",
            "PARTIAL",
            "CROSSED_BOOK",
        ]
    ]
    provenance: Provenance


def market_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:quanthecy:market-observation:1.0.0",
        **MarketObservation.model_json_schema(),
    }
