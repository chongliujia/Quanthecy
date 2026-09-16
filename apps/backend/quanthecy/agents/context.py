import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from quanthecy_analytics.intelligence import digest
from quanthecy_analytics.signals import BAD_FLAGS, analyze

from quanthecy.markets.repositories import history_repository
from quanthecy.research.services import comparisons, timeline


def build_context(market_id: UUID, cutoff: datetime) -> dict[str, Any]:
    rows = history_repository().history(
        market_id,
        start=(cutoff - timedelta(minutes=20)).isoformat(),
        end=cutoff.isoformat(),
        known_at=cutoff.isoformat(),
        limit=1001,
    )
    rows = sorted(
        [
            row
            for row in rows
            if datetime.fromisoformat(row["recorded_at"]) <= cutoff
            and datetime.fromisoformat(row["received_at"]) <= cutoff
        ],
        key=lambda row: (row["received_at"], row["observation_id"]),
    )
    if not rows or len(rows) > 1000:
        raise ValidationError("No complete bounded history available.")
    metrics, signals = analyze(rows)
    latest = rows[-1]
    entries = timeline(market_id, cutoff)
    reviews = [
        review
        for review in comparisons(cutoff)
        if market_id in (review.left_snapshot.market.id, review.right_snapshot.market.id)
    ]
    references: list[dict[str, Any]] = [
        {
            "id": "market",
            "kind": "market",
            "label": latest["market"]["title"],
            "value": {
                "platform": latest["platform"],
                "outcome": latest["outcome"],
                "observed_at": latest["received_at"],
                "probability": latest["probability"],
                "best_bid": latest["best_bid"],
                "best_ask": latest["best_ask"],
                "liquidity": latest["liquidity"],
                "quality_flags": latest["quality_flags"],
            },
        },
        {
            "id": "rules",
            "kind": "rules",
            "label": "Contract resolution rules",
            "value": latest["market"],
        },
    ]
    for name in ("probability_change_15m", "spread_change_15m", "volume_zscore"):
        references.append(
            {
                "id": f"metric:{name}",
                "kind": "metric",
                "label": name.replace("_", " "),
                "value": {
                    "value": metrics[name],
                    "unit": "probability_fraction" if "change" in name else "z_score",
                    "calculation": metrics,
                },
            }
        )
    for signal in signals:
        references.append(
            {"id": signal["id"], "kind": "signal", "label": signal["signal_type"], "value": signal}
        )
    for entry in entries.items[:8]:
        references.append(
            {
                "id": str(entry.evidence.revision_id),
                "kind": "evidence",
                "label": entry.evidence.title,
                "url": entry.evidence.url,
                "value": entry.model_dump(mode="json"),
            }
        )
    for review in reviews[:5]:
        references.append(
            {
                "id": str(review.id),
                "kind": "comparison",
                "label": review.title,
                "value": review.model_dump(mode="json"),
            }
        )
    limitations = [
        "REST snapshots; exchange quote time is unavailable. "
        "Topic and timing do not establish causation."
    ]
    if not metrics["history_ready"]:
        limitations.append(f"Analytics unavailable: {metrics['reason']}.")
    if (cutoff - datetime.fromisoformat(latest["received_at"])).total_seconds() > 180:
        limitations.append("The latest available quote is stale at the research cutoff.")
    if not entries.items:
        limitations.append("No associated news evidence was available at this cutoff.")
    if not reviews:
        limitations.append("No reviewed cross-platform comparison available.")
    if len(entries.items) > 8 or entries.truncated or len(reviews) > 5:
        limitations.append(
            "Evidence context is bounded to eight news revisions and five comparisons."
        )
    stale = (cutoff - datetime.fromisoformat(latest["received_at"])).total_seconds() > 180
    quality = {
        "history_ready": metrics["history_ready"],
        "stale": stale,
        "forecast_eligible": bool(
            metrics["history_ready"]
            and not stale
            and entries.items
            and latest["probability"]
            and latest["probability"]["basis"] == "MIDPOINT"
            and not BAD_FLAGS.intersection(latest["quality_flags"])
            and latest["market"]["status"] == "OPEN"
            and latest["market"]["resolution_rules"].strip()
            and latest["market"]["closes_at"]
            and datetime.fromisoformat(latest["market"]["closes_at"]) > cutoff
        ),
    }
    context = {
        "version": "context-v2",
        "cutoff": cutoff.isoformat(),
        "references": references,
        "limitations": limitations,
        "quality": quality,
    }
    if len(json.dumps(context)) > 48000:
        raise ValidationError("context_too_large")
    # Full immutable inputs stay in our database; the model receives references and metrics only.
    return {
        **context,
        "observations": rows,
        "manifest": {
            "sha256": digest(context),
            "reference_count": len(references),
            "observation_count": len(rows),
            "window_minutes": 20,
            "observation_sha256": digest(rows),
        },
    }
