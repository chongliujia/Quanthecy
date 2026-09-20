# Frozen quality policy for rest-window-v2 replay. Do not use for new research.
"""Versioned eligibility checks for normalized research data, not forecast accuracy."""

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

VERSION = "research-quality-v1"
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
    if any(b["value"] < a["value"] for a, b in zip(activities, activities[1:], strict=False)):
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
