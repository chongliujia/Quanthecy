# Frozen historical replay implementation. New research uses signals.analyze.
"""Versioned deterministic research signals using observed REST sampling times."""

import math
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .quality_v1 import BAD_FLAGS, window_quality

VERSION = "rest-window-v2"
PARAMETERS = {
    "window_seconds": 900,
    "max_gap_seconds": 150,
    "minimum_samples": 10,
    "probability_change": 0.05,
    "spread_widening": 0.03,
    "volume_zscore": 3.0,
    "volume_rate_ratio": 2.0,
}


def analyze(
    observations: list[dict[str, Any]], *, truncated: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    unique = {o["observation_id"]: o for o in observations}
    rows = sorted(unique.values(), key=lambda o: (o["received_at"], o["observation_id"]))
    metrics: dict[str, Any] = {
        "version": VERSION,
        "parameters": PARAMETERS,
        "probability_change_15m": None,
        "spread_change_15m": None,
        "volume_zscore": None,
        "history_ready": False,
        "reason": "insufficient_history",
    }

    def unavailable(reason: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        metrics["reason"] = reason
        metrics["quality"] = window_quality(rows, reason).model_dump()
        return metrics, []

    if truncated:
        return unavailable("history_truncated")
    if not rows:
        return unavailable("insufficient_history")
    if any(unique[o["observation_id"]] != o for o in observations):
        return unavailable("conflicting_duplicate")
    last = rows[-1]
    end = datetime.fromisoformat(last["received_at"])
    cutoff = end - timedelta(seconds=PARAMETERS["window_seconds"])
    before = [i for i, o in enumerate(rows) if datetime.fromisoformat(o["received_at"]) <= cutoff]
    if not before:
        return unavailable("insufficient_history")
    rows = rows[before[-1] :]
    times = [datetime.fromisoformat(o["received_at"]) for o in rows]
    deltas = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    if (cutoff - times[0]).total_seconds() > PARAMETERS["max_gap_seconds"] or len(
        rows
    ) < PARAMETERS["minimum_samples"]:
        return unavailable("insufficient_history")
    if any(d <= 0 or d > PARAMETERS["max_gap_seconds"] for d in deltas) or any(
        BAD_FLAGS.intersection(o["quality_flags"]) for o in rows
    ):
        return unavailable("sampling_gap_or_invalid_quote")
    if (
        len({(o["market"]["id"], o["outcome"]["id"], o["market"]["rules_version"]) for o in rows})
        != 1
    ):
        return unavailable("incompatible_observations")
    if any(o["market"]["status"] != "OPEN" for o in rows):
        return unavailable("market_not_open")
    if any(not o["market"]["resolution_rules"].strip() for o in rows):
        return unavailable("missing_resolution_rules")
    quality = window_quality(rows)
    if quality.common_reasons:
        return unavailable(quality.common_reasons[0])
    metrics.update(
        history_ready=True,
        reason=None,
        window_start=rows[0]["received_at"],
        window_end=last["received_at"],
        sample_count=len(rows),
        quality=quality.model_dump(),
    )
    signals = []

    def emit(kind: str, magnitude: float, threshold: float) -> None:
        signals.append(
            {
                "id": str(
                    uuid5(NAMESPACE_URL, f"quanthecy/{VERSION}/{last['observation_id']}/{kind}")
                ),
                "version": VERSION,
                "parameters": PARAMETERS,
                "signal_type": kind,
                "market_id": last["market"]["id"],
                "outcome_id": last["outcome"]["id"],
                "received_at": last["received_at"],
                "score": min(1.0, magnitude / (threshold * 2)),
                "metrics": metrics,
                "observation_ids": [o["observation_id"] for o in rows],
            }
        )

    probabilities = [o["probability"] for o in rows]
    if quality.price_usable:
        change = probabilities[-1]["value"] - probabilities[0]["value"]
        metrics["probability_change_15m"] = change
        if abs(change) >= PARAMETERS["probability_change"]:
            emit(
                "PROBABILITY_SPIKE" if change > 0 else "PROBABILITY_DROP",
                abs(change),
                PARAMETERS["probability_change"],
            )
        if all(o["best_bid"] is not None and o["best_ask"] is not None for o in rows):
            spread_change = (last["best_ask"] - last["best_bid"]) - (
                rows[0]["best_ask"] - rows[0]["best_bid"]
            )
            metrics["spread_change_15m"] = spread_change
            if spread_change >= PARAMETERS["spread_widening"]:
                emit("SPREAD_WIDENING", spread_change, PARAMETERS["spread_widening"])
    volumes = [o["volume"] for o in rows]
    if quality.volume_usable:
        rates = [
            (b["value"] - a["value"]) / d
            for a, b, d in zip(volumes, volumes[1:], deltas, strict=False)
        ]
        if all(r >= 0 and math.isfinite(r) for r in rates):
            baseline, current = rates[:-1], rates[-1]
            deviation = pstdev(baseline)
            metrics["volume_unit"] = volumes[-1]["unit"]
            metrics["volume_rate"] = current
            if deviation > 1e-12:
                zscore = (current - mean(baseline)) / deviation
                metrics["volume_zscore"] = zscore
                if (
                    zscore >= PARAMETERS["volume_zscore"]
                    and current >= mean(baseline) * PARAMETERS["volume_rate_ratio"]
                ):
                    emit("VOLUME_SPIKE", zscore, PARAMETERS["volume_zscore"])
            else:
                quality.volume_usable = False
                quality.volume_reasons.append("constant_volume_baseline")
        else:
            quality.volume_usable = False
            quality.volume_reasons.append("invalid_volume_rate")
    metrics["quality"] = quality.model_dump()
    return metrics, signals
