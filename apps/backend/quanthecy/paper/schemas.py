from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field


class PolicyOut(Schema):
    entry_change_15m: Decimal
    market_budget_fraction: Decimal
    event_budget_fraction: Decimal
    max_spread: Decimal
    max_quote_age_seconds: int
    holding_minutes: int


class CreateInput(Schema):
    version: Literal["paper-v1", "paper-v2", "paper-v3"] = "paper-v2"
    assistant_version_ids: list[UUID] = Field(default_factory=list, max_length=3)
    daily_review_limit: int = Field(default=10, ge=1, le=20)
    name: str = Field(default="Paper trading experiment", min_length=1, max_length=120)
    market_ids: list[UUID] = Field(min_length=1, max_length=20)
    initial_cash: Decimal = Field(
        default=Decimal(10000), ge=100, le=1000000, max_digits=14, decimal_places=2
    )


class RunningInput(Schema):
    experiment_id: UUID | None = None
    running: bool


class CandidateOut(Schema):
    id: UUID
    platform: str
    title: str
    event: str
    bid: float
    ask: float


class EquityOut(Schema):
    at: datetime
    equity: Decimal | None


class AccountOut(Schema):
    id: UUID
    platform: str
    strategy: str
    label: str = ""
    assistant_version_id: UUID | None = None
    review_summary: "ReviewSummary | None" = None
    initial_cash: Decimal
    cash: Decimal
    reserved_cash: Decimal
    equity: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    fees: Decimal
    max_drawdown: Decimal
    unpriced_positions: int
    equity_at: datetime | None
    fills: int
    orders: int
    equity_history: list[EquityOut]


class PositionOut(Schema):
    id: UUID
    account_id: UUID
    market_id: UUID
    title: str
    quantity: Decimal
    cost_basis: Decimal
    opened_at: datetime


class OrderOut(Schema):
    id: UUID
    account_id: UUID
    market_id: UUID
    title: str
    side: str
    status: str
    reason: str
    quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal
    created_at: datetime
    finished_at: datetime | None


class DecisionOut(Schema):
    id: UUID
    account_id: UUID
    market_id: UUID
    title: str
    action: str
    reason: str
    created_at: datetime


class UpgradeInput(Schema):
    daily_review_limit: int = Field(default=10, ge=1, le=20)


class ExperimentOut(Schema):
    id: UUID
    name: str
    version: str
    running: bool
    created_at: datetime


class ReviewSummary(Schema):
    model_ready: bool
    model: str
    daily_limit: int
    calls_today: int
    calls_remaining: int
    candidates: int
    reviewed: int
    allowed: int
    rejected: int
    abstained: int
    invalidated: int
    failed: int
    waiting: int
    paired_candidates: int
    paired_agent_entries: int
    participation: float | None
    provider_calls: int
    prompt_tokens: int
    completion_tokens: int
    average_latency_seconds: float | None
    average_queue_seconds: float | None
    model_cost_usd: Decimal | None = None


class ReviewOut(Schema):
    id: UUID
    market_id: UUID
    title: str
    detected_at: datetime
    expires_at: datetime
    state: str
    reason: str
    run_state: str | None
    review_decision: str | None
    model: str | None
    error_code: str
    baseline_filled: bool
    agent_filled: bool
    account_id: UUID | None = None
    assistant_label: str = ""
    run_id: UUID | None = None


class ReviewDetail(ReviewOut):
    inputs: dict[str, Any]
    context: dict[str, Any] | None
    report: dict[str, Any] | None
    usage: dict[str, Any]
    finished_at: datetime | None


class LabOut(Schema):
    experiments: list[ExperimentOut]
    is_latest: bool
    review_summary: ReviewSummary | None
    recent_reviews: list[ReviewOut]
    id: UUID
    name: str
    running: bool
    version: str
    settings: dict[str, Any]
    checked_at: datetime | None
    created_at: datetime
    error_code: str
    collector: dict[str, Any]
    market_count: int
    market_ids: list[UUID] = Field(default_factory=list)
    accounts: list[AccountOut]
    positions: list[PositionOut]
    recent_orders: list[OrderOut]
    recent_decisions: list[DecisionOut]


class FillOut(Schema):
    quantity: Decimal
    price: Decimal
    fee: Decimal
    cash_delta: Decimal
    realized_pnl: Decimal
    quote_id: UUID | None
    created_at: datetime


class OrderDetail(OrderOut):
    inputs: dict[str, Any]
    execution_quote: dict[str, Any] | None
    fills: list[FillOut]
    replay_matches: bool | None
