"""Deterministic sampled quote windows for user rules; no model or network calls."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .quality import STALE_SECONDS, window_quality

VERSION = "watchlist-window-v1"
MAX_GAP_SECONDS = 150
MINIMUM_SAMPLES = {5: 4, 15: 10, 60: 40}


def evaluate_window(
    observations: list[dict[str, Any]],
    *,
    window_minutes: int,
    kind: str,
    observation_id: str,
    now: datetime,
    truncated: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": VERSION,
        "eligible": False,
        "reason": "insufficient_history",
        "value_pp": None,
        "inputs": [],
        "window_start": None,
        "window_end": None,
        "max_gap_seconds": MAX_GAP_SECONDS,
        "minimum_samples": MINIMUM_SAMPLES[window_minutes],
    }

    def blocked(reason: str) -> dict[str, Any]:
        result["reason"] = reason
        return result

    if truncated:
        return blocked("history_truncated")
    unique = {o["observation_id"]: o for o in observations}
    if any(unique[o["observation_id"]] != o for o in observations):
        return blocked("conflicting_duplicate")
    rows = sorted(unique.values(), key=lambda o: datetime.fromisoformat(o["received_at"]))
    if not rows or rows[-1]["observation_id"] != observation_id:
        return blocked("analytics_pending")
    end = datetime.fromisoformat(rows[-1]["received_at"])
    if not 0 <= (now - end).total_seconds() <= STALE_SECONDS:
        return blocked("stale_observation")
    cutoff = end - timedelta(minutes=window_minutes)
    before = [i for i, r in enumerate(rows) if datetime.fromisoformat(r["received_at"]) <= cutoff]
    if not before:
        return result
    rows = rows[before[-1] :]
    times = [datetime.fromisoformat(r["received_at"]) for r in rows]
    if (
        len(rows) < MINIMUM_SAMPLES[window_minutes]
        or (cutoff - times[0]).total_seconds() > MAX_GAP_SECONDS
    ):
        return result
    if any(
        not 0 < (b - a).total_seconds() <= MAX_GAP_SECONDS
        for a, b in zip(times, times[1:], strict=False)
    ):
        return blocked("sampling_gap_or_invalid_quote")
    if any(datetime.fromisoformat(r["recorded_at"]) > now for r in rows):
        return blocked("future_observation")
    if (
        len({(r["market"]["id"], r["outcome"]["id"], r["market"]["rules_version"]) for r in rows})
        != 1
    ):
        return blocked("incompatible_observations")
    quality = window_quality(rows)
    if not quality.price_usable:
        return blocked((quality.common_reasons + quality.price_reasons)[0])
    quote_time = datetime.fromisoformat(rows[-1]["probability"]["as_of"])
    if not 0 <= (now - quote_time).total_seconds() <= STALE_SECONDS:
        return blocked("stale_price")
    # Decimal arithmetic avoids surprising threshold comparisons such as 0.5 pp.
    start, last = rows[0], rows[-1]
    if kind == "PROBABILITY_MOVE":
        change = Decimal(str(last["probability"]["value"])) - Decimal(
            str(start["probability"]["value"])
        )
    elif kind == "SPREAD_WIDENING":
        change = (Decimal(str(last["best_ask"])) - Decimal(str(last["best_bid"]))) - (
            Decimal(str(start["best_ask"])) - Decimal(str(start["best_bid"]))
        )
    else:
        raise ValueError("Unsupported alert metric")
    result.update(
        eligible=True,
        reason="",
        value_pp=float(change * 100),
        window_start=start["received_at"],
        window_end=last["received_at"],
        limitations=quality.limitations,
        inputs=[
            {
                "observation_id": r["observation_id"],
                "received_at": r["received_at"],
                "recorded_at": r["recorded_at"],
                "best_bid": r["best_bid"],
                "best_ask": r["best_ask"],
                "probability": r["probability"],
                "rules_version": r["market"]["rules_version"],
                "quality_flags": r["quality_flags"],
            }
            for r in rows
        ],
    )
    return result
