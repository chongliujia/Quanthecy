from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field
from quanthecy_analytics.contracts.market import MarketObservation
from quanthecy_analytics.quality import ResearchQuality, WindowQuality, research_quality


class Metrics(Schema):
    version: str
    parameters: dict[str, float]
    probability_change_15m: float | None = None
    spread_change_15m: float | None = None
    volume_zscore: float | None = None
    history_ready: bool
    reason: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int | None = None
    volume_unit: str | None = None
    volume_rate: float | None = None
    quality: WindowQuality | None = None


class MarketSummary(Schema):
    id: UUID
    platform: Literal["polymarket", "kalshi"]
    exchange_id: str
    title: str
    status: str
    first_observed_at: datetime
    last_observed_at: datetime
    stale: bool
    probability: float | None
    best_bid: float | None
    best_ask: float | None
    quality_flags: list[str]
    metrics: Metrics
    data_quality: ResearchQuality


class MarketPage(Schema):
    items: list[MarketSummary]
    total: int
    offset: int
    limit: int
    coverage: str = "Selected binary YES outcomes; REST snapshots from collection start."


class MarketDetail(MarketSummary):
    latest: MarketObservation
    live_cache: bool


class HistoryPage(Schema):
    items: list[MarketObservation]
    start: datetime
    end: datetime
    truncated: bool


class CollectionSource(Schema):
    platform: str
    state: Literal["recent", "delayed", "empty"]
    latest_observation: datetime | None
    delay_seconds: int | None
    total_markets: int
    fresh_markets: int
    collector_checked_at: datetime | None
    error_code: Literal["network", "rate_limited", "exchange", "invalid_data", "storage"] | None
    run_state: Literal[
        "active",
        "paused",
        "pause_pending",
        "configuration_pending",
        "request_failed",
        "no_heartbeat",
        "delayed",
        "unknown",
    ] = "unknown"
    managed: bool = False
    enabled_targets: int | None = None
    desired_revision: int | None = None
    applied_revision: int | None = None


class CollectionStatus(Schema):
    checked_at: datetime
    sources: list[CollectionSource]
    analytics_state: Literal["active", "no_heartbeat", "unavailable"] = "unavailable"
    analytics_checked_at: datetime | None = None


class SignalOut(Schema):
    id: UUID
    version: str
    parameters: dict[str, float]
    signal_type: Literal["PROBABILITY_SPIKE", "PROBABILITY_DROP", "SPREAD_WIDENING", "VOLUME_SPIKE"]
    market_id: UUID
    outcome_id: UUID
    received_at: datetime
    score: float = Field(ge=0, le=1)
    metrics: Metrics
    observation_ids: list[UUID]


def summary_values(market: Any, stale: bool, at: datetime) -> dict[str, Any]:
    row = market.latest
    return {
        "id": market.id,
        "platform": market.platform,
        "exchange_id": market.exchange_id,
        "title": market.title,
        "status": market.status,
        "first_observed_at": market.first_observed_at,
        "last_observed_at": market.last_observed_at,
        "stale": stale,
        "probability": (row["probability"] or {}).get("value"),
        "best_bid": row["best_bid"],
        "best_ask": row["best_ask"],
        "quality_flags": row["quality_flags"],
        "metrics": market.metrics,
        "data_quality": research_quality(row, market.metrics, at),
    }
