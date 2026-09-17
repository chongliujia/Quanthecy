"""Bounded, backward-only alignment of REST quotes, never a probability distribution."""

from datetime import datetime, timedelta
from typing import Any

from .quality import window_quality

STEP_SECONDS = 60
MAX_AGE_SECONDS = 90


def align_contract(
    rows: list[dict[str, Any]], *, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    # Availability, not publication time, determines whether a quote was knowable.
    ordered = sorted(
        (
            (
                max(
                    datetime.fromisoformat(r["received_at"]),
                    datetime.fromisoformat(r["recorded_at"]),
                ),
                r,
            )
            for r in rows
        ),
        key=lambda item: (item[0], item[1]["received_at"], item[1]["observation_id"]),
    )
    axis = [start]
    tick = start.replace(second=0, microsecond=0) + timedelta(seconds=STEP_SECONDS)
    while tick < end:
        axis.append(tick)
        tick += timedelta(seconds=STEP_SECONDS)
    if end > start:
        axis.append(end)
    prepared = [(available, row, window_quality([row]).price_usable) for available, row in ordered]
    points: list[dict[str, Any]] = []
    index = -1
    for at in axis:
        while index + 1 < len(prepared) and prepared[index + 1][0] <= at:
            index += 1
        point: dict[str, Any] = {
            "at": at,
            "probability": None,
            "observed_at": None,
            "observation_id": None,
            "issue": "missing",
        }
        if index >= 0:
            _, row, usable = prepared[index]
            observed = datetime.fromisoformat(row["received_at"])
            price = row["probability"]
            point.update(observed_at=observed, observation_id=row["observation_id"])
            if row.get("contract_changed"):
                point["issue"] = "contract_changed"
            elif not usable:
                point["issue"] = "invalid_quote"
            elif not price or any(
                not 0 <= (at - stamp).total_seconds() <= MAX_AGE_SECONDS
                for stamp in (observed, datetime.fromisoformat(price["as_of"]))
            ):
                point["issue"] = "stale"
            else:
                point.update(probability=price["value"], issue=None)
        points.append(point)
    return points
