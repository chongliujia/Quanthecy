"""Deterministic, long-YES paper execution. Never sends exchange orders."""

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "paper-v1"
ZERO = Decimal("0")
ONE = Decimal("1")
MONEY = Decimal("0.000001")
Finite = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class Level(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Annotated[Decimal, Field(gt=0, lt=1, allow_inf_nan=False)]
    size: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class ExecutionQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    quote_id: UUID
    market_id: UUID
    platform: Literal["polymarket", "kalshi"]
    exchange_id: str = Field(min_length=1, max_length=255)
    outcome_id: str = Field(min_length=1, max_length=255)
    received_at: datetime
    recorded_at: datetime
    metadata_at: datetime
    source_at: datetime | None
    status: Literal["OPEN", "CLOSED", "RESOLVED", "UNKNOWN"]
    settlement: Literal[0, 1] | None
    bids: list[Level] = Field(max_length=100)
    asks: list[Level] = Field(max_length=100)
    fee_rate: Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)] | None
    fee_model: Literal["polymarket_quadratic", "kalshi_quadratic", "unknown"]
    fee_source: str = Field(max_length=1000)
    source: str = Field(max_length=1000)
    raw: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_book(self) -> "ExecutionQuote":
        for at in [self.received_at, self.recorded_at, self.metadata_at, self.source_at]:
            if at is not None and (at.tzinfo is None or at.utcoffset() is None):
                raise ValueError("Execution timestamps must be timezone aware")
        if self.metadata_at > self.received_at or self.recorded_at < self.received_at:
            raise ValueError("Inconsistent acquisition times")
        self.bids.sort(key=lambda level: level.price, reverse=True)
        self.asks.sort(key=lambda level: level.price)
        for side in [self.bids, self.asks]:
            if len({level.price for level in side}) != len(side):
                raise ValueError("Duplicate price levels")
        if self.bids and self.asks and self.bids[0].price > self.asks[0].price:
            raise ValueError("Crossed order book")
        if self.settlement is not None and self.status != "RESOLVED":
            raise ValueError("Payout requires sourced final settlement")
        return self


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def fee(quantity: Decimal, price: Decimal, quote: ExecutionQuote) -> Decimal:
    if quote.fee_rate is None or quote.fee_model == "unknown":
        raise ValueError("Fee parameters unavailable")
    value = quote.fee_rate * quantity * price * (ONE - price)
    if quote.fee_model == "kalshi_quadratic":
        return value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return value.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def quote_issue(quote: ExecutionQuote | None, now: datetime) -> str:
    if quote is None:
        return "awaiting_orderbook"
    if quote.recorded_at > now or not 0 <= (now - quote.received_at).total_seconds() <= 90:
        return "stale_orderbook"
    if not 0 <= (quote.received_at - quote.metadata_at).total_seconds() <= 120:
        return "stale_metadata"
    if quote.status != "OPEN":
        return "market_not_open"
    if not quote.bids or not quote.asks:
        return "missing_two_sided_quote"
    if quote.fee_rate is None or quote.fee_model == "unknown":
        return "unknown_fees"
    if quote.asks[0].price - quote.bids[0].price > Decimal("0.08"):
        return "spread_above_limit"
    return ""


class SimulatedFill(BaseModel):
    quantity: Decimal
    price: Decimal
    fee: Decimal
    book_price: Decimal


def match_order(
    *,
    quote: ExecutionQuote,
    side: Literal["BUY", "SELL"],
    quantity: Decimal,
    limit_price: Decimal,
    budget: Decimal,
    slippage_bps: int = 10,
) -> list[SimulatedFill]:
    """IOC against at most 10% of each visible level; integer shares, adverse slippage.

    Different strategy accounts are independent counterfactuals. A single order
    consumes a quote only once. No maker queue, hidden liquidity or fills are invented.
    """
    if quantity <= 0 or budget < 0 or slippage_bps < 0:
        return []
    remaining = quantity.to_integral_value(rounding=ROUND_DOWN)
    fills = []
    for level in quote.asks if side == "BUY" else quote.bids:
        adjustment = Decimal(slippage_bps) / Decimal(10000)
        price = money(level.price * (ONE + adjustment if side == "BUY" else ONE - adjustment))
        if not ZERO < price < ONE:
            continue
        if (side == "BUY" and price > limit_price) or (side == "SELL" and price < limit_price):
            break
        available = (level.size * Decimal("0.1")).to_integral_value(rounding=ROUND_DOWN)
        take = min(remaining, available)
        if side == "BUY":
            rate = quote.fee_rate
            if rate is None:
                raise ValueError("Unknown fee rate")
            unit_cost = price + rate * price * (ONE - price)
            take = min(take, (budget / unit_cost).to_integral_value(rounding=ROUND_DOWN))
            while take > 0 and money(take * price) + fee(take, price, quote) > budget:
                take -= ONE
        if take <= 0:
            continue
        cost = fee(take, price, quote)
        fills.append(SimulatedFill(quantity=take, price=price, fee=cost, book_price=level.price))
        remaining -= take
        if side == "BUY":
            budget -= money(take * price) + cost
        if remaining <= 0:
            break
    return fills
