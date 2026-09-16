"""Public collection health derived from persisted observations and ephemeral telemetry."""

import json
from datetime import datetime, timedelta
from typing import Any, Literal

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone
from redis import Redis

from .models import Market
from .schemas import CollectionSource, CollectionStatus

ERROR_CODES = {"network", "rate_limited", "exchange", "invalid_data", "storage"}


def collection_status() -> CollectionStatus:
    now = timezone.now()
    summaries = {
        row["platform"]: row
        for row in Market.objects.values("platform").annotate(
            total=Count("id"),
            fresh=Count(
                "id", filter=Q(status="OPEN", last_observed_at__gte=now - timedelta(seconds=180))
            ),
            latest=Max("last_observed_at"),
        )
    }
    telemetry: list[Any] = [None, None]
    platforms = ("polymarket", "kalshi")
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
        ) as cache:
            telemetry = cache.mget([f"collector:status:{platform}" for platform in platforms])
    except Exception:
        pass  # Redis loss must not hide persisted data freshness.
    sources = []
    for platform, raw in zip(platforms, telemetry, strict=True):
        checked_at = None
        error = None
        try:
            record = json.loads(raw) if raw else {}
            at = datetime.fromisoformat(record["checked_at"])
            if at.tzinfo is not None and 0 <= (now - at).total_seconds() <= 300:
                checked_at = at
                error = record.get("error_code")
                error = error if error in ERROR_CODES else None
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        summary = summaries.get(platform, {})
        latest = summary.get("latest")
        delay = max(0, int((now - latest).total_seconds())) if latest else None
        state: Literal["empty", "delayed", "recent"] = (
            "empty" if delay is None else "delayed" if delay > 180 else "recent"
        )
        sources.append(
            CollectionSource(
                platform=platform,
                state=state,
                latest_observation=latest,
                delay_seconds=delay,
                total_markets=summary.get("total", 0),
                fresh_markets=summary.get("fresh", 0),
                collector_checked_at=checked_at,
                error_code=error,
            )
        )
    return CollectionStatus(checked_at=now, sources=sources)
