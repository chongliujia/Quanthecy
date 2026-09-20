"""Versioned eligibility checks for normalized research data, not forecast accuracy."""

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .volume import cumulative_delta

VERSION = "research-quality-v2"
STALE_SECONDS = 180
BAD_FLAGS = {"GAP", "OUT_OF_ORDER", "STALE", "CROSSED_BOOK"}


class WindowQuality(BaseModel):
    version: str = VERSION
    observation_id: str | None = None
    price_usable: bool = False
    volume_usable: bool = False
    common_reasons: list[str] = Field(default_factory=list)
    price_reasons: list[str] = Field(default_factory=list)
    volume_reasons: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ResearchQuality(BaseModel):
    version: str = VERSION
    checked_at: datetime
    state: Literal["ready", "limited", "blocked"]
    price_usable: bool
    volume_usable: bool
    reasons: list[str]
    limitations: list[str]
    age_seconds: int | None


def finite(value: Any, *, probability: bool = False) -> bool:
    return (
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        and (not probability or value <= 1)
    )


def quote_reasons(row: dict[str, Any]) -> list[str]:
    probability = row["probability"]
    bid, ask = row["best_bid"], row["best_ask"]
    if probability is None:
        return ["missing_midpoint"]
    if probability["basis"] != "MIDPOINT":
        return ["unsupported_price_basis"]
    if not all(finite(value, probability=True) for value in (bid, ask, probability["value"])):
        return ["invalid_quote"]
    if not 0 < bid <= ask < 1:
        return ["invalid_quote"]
    if not math.isclose(probability["value"], (bid + ask) / 2, abs_tol=1e-9, rel_tol=0):
        return ["midpoint_mismatch"]
    age = (
        datetime.fromisoformat(row["received_at"]) - datetime.fromisoformat(probability["as_of"])
    ).total_seconds()
    return ["invalid_price_time"] if not 0 <= age <= STALE_SECONDS else []


def window_quality(rows: list[dict[str, Any]], reason: str | None = None) -> WindowQuality:
    common = {reason} if reason else set()
    price: set[str] = set()
    volume: set[str] = set()
    limitations: set[str] = set()
    if not rows:
        common.add("insufficient_history")
    for row in rows:
        if BAD_FLAGS.intersection(row["quality_flags"]):
            common.add("quality_flags_excluded")
        # Current adapters mark missing bid/ask, volume or rules as PARTIAL.
        # Check those fields separately; an unexplained partial flag fails closed.
        if "PARTIAL" in row["quality_flags"] and not (
            row["best_bid"] is None
            or row["best_ask"] is None
            or row["volume"] is None
            or not row["market"]["resolution_rules"].strip()
        ):
            common.add("quality_flags_excluded")
        if row["market"]["status"] != "OPEN":
            common.add("market_not_open")
        if not row["market"]["resolution_rules"].strip():
            common.add("missing_resolution_rules")
        if datetime.fromisoformat(row["recorded_at"]) < datetime.fromisoformat(row["received_at"]):
            common.add("invalid_recording_time")
        price.update(quote_reasons(row))
        activity = row["volume"]
        if activity is None:
            volume.add("missing_volume")
        elif not finite(activity["value"]) or activity["window_start"] is not None:
            volume.add("invalid_volume")
        elif (
            not 0
            <= (
                datetime.fromisoformat(row["received_at"])
                - datetime.fromisoformat(activity["as_of"])
            ).total_seconds()
            <= STALE_SECONDS
        ):
            volume.add("invalid_volume_time")
        if "SOURCE_TIME_MISSING" in row["quality_flags"] or row["event_at"] is None:
            limitations.add("source_time_missing")
        if row["liquidity"] is None:
            limitations.add("liquidity_unavailable")
    if len({r["probability"]["source"] for r in rows if r["probability"]}) > 1:
        price.add("price_source_changed")
    activities = [r["volume"] for r in rows if r["volume"] is not None]
    if len({(v["unit"], v["basis"]) for v in activities}) > 1:
        volume.add("volume_basis_changed")
    if all(finite(v["value"]) for v in activities) and any(
        cumulative_delta(a["value"], b["value"]) < 0
        for a, b in zip(activities, activities[1:], strict=False)
    ):
        volume.add("volume_counter_reset")
    return WindowQuality(
        observation_id=rows[-1]["observation_id"] if rows else None,
        price_usable=not common and not price,
        volume_usable=not common and not volume,
        common_reasons=sorted(common),
        price_reasons=sorted(price),
        volume_reasons=sorted(volume),
        limitations=sorted(limitations),
    )


def research_quality(
    latest: dict[str, Any], metrics: dict[str, Any], at: datetime
) -> ResearchQuality:
    """Combine persisted window checks with freshness at the explicit research cutoff."""
    current = window_quality([latest])
    common = set(current.common_reasons)
    price = set(current.price_reasons)
    volume = set(current.volume_reasons)
    limitations = set(current.limitations)
    received = datetime.fromisoformat(latest["received_at"])
    age = int((at - received).total_seconds())
    if received > at or datetime.fromisoformat(latest["recorded_at"]) > at:
        common.add("future_observation")
    elif (at - received).total_seconds() > STALE_SECONDS:
        common.add("stale_observation")
    for field, reasons, code in (
        ("probability", price, "invalid_price_time"),
        ("volume", volume, "invalid_volume_time"),
    ):
        value = latest[field]
        if (
            value
            and not 0
            <= (at - datetime.fromisoformat(value["as_of"])).total_seconds()
            <= STALE_SECONDS
        ):
            reasons.add(code)
    saved = metrics.get("quality") or {}
    if saved.get("version") != VERSION:
        common.add("quality_not_evaluated")
    elif saved.get("observation_id") != latest["observation_id"]:
        common.add("analytics_pending")
    else:
        checked = WindowQuality.model_validate(saved)
        common.update(checked.common_reasons)
        price.update(checked.price_reasons)
        volume.update(checked.volume_reasons)
        limitations.update(checked.limitations)
    if not metrics.get("history_ready"):
        common.add(metrics.get("reason") or "insufficient_history")
    price_usable = not common and not price
    volume_usable = not common and not volume
    return ResearchQuality(
        checked_at=at,
        state="ready"
        if price_usable and volume_usable
        else ("limited" if price_usable or volume_usable else "blocked"),
        price_usable=price_usable,
        volume_usable=volume_usable,
        reasons=sorted(common | price | volume),
        limitations=sorted(limitations),
        age_seconds=age,
    )
