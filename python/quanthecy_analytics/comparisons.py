"""Bounded, deterministic comparison with explicit information availability."""

from datetime import UTC, datetime
from typing import Any

MAX_AGE_SECONDS = 180
MAX_SKEW_SECONDS = 90
EXCLUDED_FLAGS = {"STALE", "GAP", "OUT_OF_ORDER", "CROSSED_BOOK", "PARTIAL"}


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def available_at(row: dict[str, Any]) -> datetime:
    return max(timestamp(row["received_at"]), timestamp(row["recorded_at"]))


def compare(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    review: dict[str, Any] | None,
    at: datetime,
) -> dict[str, Any]:
    issues: list[str] = []
    values: list[dict[str, Any] | None] = []
    if review is None:
        issues.append("NO_REVIEW_AT_TIME")
    elif review["relation"] == "INCOMPATIBLE":
        issues.append("INCOMPATIBLE_RULES")
    for side, row in (("left", left), ("right", right)):
        prefix = side.upper()
        if row is None or available_at(row) > at:
            issues.append(f"{prefix}_NO_OBSERVATION")
            values.append(None)
            continue
        probability = row["probability"]
        quote = {
            "observation_id": row["observation_id"],
            "received_at": row["received_at"],
            "recorded_at": row["recorded_at"],
            "probability": probability["value"] if probability else None,
            "bid": row["best_bid"],
            "ask": row["best_ask"],
            "basis": probability["basis"] if probability else None,
            "source": probability["source"] if probability else None,
            "quality_flags": row["quality_flags"],
        }
        if review and side == "right" and review["alignment"] == "COMPLEMENT":
            quote["probability"] = 1 - quote["probability"] if probability else None
            quote["bid"] = 1 - row["best_ask"] if row["best_ask"] is not None else None
            quote["ask"] = 1 - row["best_bid"] if row["best_bid"] is not None else None
        values.append(quote)
        if (at - timestamp(row["received_at"])).total_seconds() > MAX_AGE_SECONDS:
            issues.append(f"{prefix}_STALE")
        if probability is None:
            issues.append(f"{prefix}_NO_PRICE")
        if row["market"]["status"] != "OPEN":
            issues.append(f"{prefix}_CLOSED")
        if EXCLUDED_FLAGS.intersection(row["quality_flags"]):
            issues.append(f"{prefix}_QUALITY_EXCLUDED")
        if review:
            frozen = review[f"{side}_snapshot"]
            if row["market"]["rules_version"] != frozen["market"]["rules_version"]:
                issues.append(f"{prefix}_REVIEW_OUTDATED")
            if (
                row["market"]["id"] != frozen["market"]["id"]
                or row["outcome"]["id"] != frozen["outcome"]["id"]
            ):
                issues.append(f"{prefix}_OUTCOME_MISMATCH")
    skew = None
    left_quote, right_quote = values
    if left_quote is not None and right_quote is not None:
        skew = abs(
            (
                timestamp(left_quote["received_at"]) - timestamp(right_quote["received_at"])
            ).total_seconds()
        )
        if skew > MAX_SKEW_SECONDS:
            issues.append("OBSERVATION_SKEW")
        if left_quote["basis"] != right_quote["basis"]:
            issues.append("BASIS_MISMATCH")
    delta = None
    if not issues and left_quote is not None and right_quote is not None:
        delta = left_quote["probability"] - right_quote["probability"]
    return {
        "at": at,
        "left": values[0],
        "right": values[1],
        "difference": delta,
        "skew_seconds": skew,
        "issues": issues,
        "review_version": review["version"] if review else None,
    }


def aligned_history(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    times: list[datetime],
) -> list[dict[str, Any]]:
    streams = [
        sorted(rows, key=lambda row: (available_at(row), row["observation_id"]))
        for rows in (left, right)
    ]
    reviews = sorted(reviews, key=lambda review: (review["reviewed_at"], review["version"]))
    cursors, review_cursor = [0, 0], 0
    latest: list[dict[str, Any] | None] = [None, None]
    review = None
    result = []
    for at in times:
        while review_cursor < len(reviews) and reviews[review_cursor]["reviewed_at"] <= at:
            review = reviews[review_cursor]
            review_cursor += 1
        for side, rows in enumerate(streams):
            while cursors[side] < len(rows) and available_at(rows[cursors[side]]) <= at:
                row = rows[cursors[side]]
                previous = latest[side]
                if previous is None or (timestamp(row["received_at"]), row["observation_id"]) > (
                    timestamp(previous["received_at"]),
                    previous["observation_id"],
                ):
                    latest[side] = row
                cursors[side] += 1
        result.append(compare(latest[0], latest[1], review, at))
    return result
