"""Public collection health derived from persisted observations and ephemeral telemetry."""

import json
from datetime import datetime, timedelta
from typing import Any, Literal

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone
from redis import Redis

from .models import CollectionTarget, Market
from .schemas import CollectionSource, CollectionStatus
from .selection import selection_status

ERROR_CODES = {"network", "rate_limited", "exchange", "invalid_data", "storage"}
ANALYTICS_KEY = "worker:market-analytics:heartbeat:v1"


def publish_analytics_heartbeat() -> None:
    with Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
    ) as cache:
        cache.set(ANALYTICS_KEY, timezone.now().isoformat(), ex=90)


def collection_status() -> CollectionStatus:
    now = timezone.now()
    summaries = {
        row["platform"]: row
        for row in Market.objects.values("platform").annotate(
            total=Count("id"),
            fresh=Count(
                "id",
                filter=Q(
                    status="OPEN",
                    last_observed_at__gte=now - timedelta(seconds=180),
                    last_observed_at__lte=now,
                ),
            ),
            latest=Max("last_observed_at"),
        )
    }
    telemetry: list[Any] = [None, None]
    platforms = ("polymarket", "kalshi")
    telemetry_available = False
    analytics_checked_at = None
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
        ) as cache:
            telemetry = cache.mget([f"collector:status:{platform}" for platform in platforms])
            telemetry_available = True
            raw_heartbeat = cache.get(ANALYTICS_KEY)
            if isinstance(raw_heartbeat, (str, bytes)):
                at = datetime.fromisoformat(
                    raw_heartbeat.decode() if isinstance(raw_heartbeat, bytes) else raw_heartbeat
                )
                if at.tzinfo is not None and 0 <= (now - at).total_seconds() <= 90:
                    analytics_checked_at = at
    except Exception:
        pass  # Redis loss must not hide persisted data freshness.
    plan = selection_status()
    counts = {
        row["platform"]: row["total"]
        for row in CollectionTarget.objects.filter(enabled=True, topic__enabled=True)
        .values("platform")
        .annotate(total=Count("exchange_id", distinct=True))
    }
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
            "empty"
            if latest is None
            else "delayed"
            if latest > now or (now - latest).total_seconds() > 180
            else "recent"
        )
        control = plan.get("sources", {}).get(platform, {})
        paused = (plan["managed"] and counts.get(platform, 0) == 0) or control.get(
            "enabled"
        ) is False
        collector_at = plan.get("checked_at") or checked_at
        run_state: Any = (
            "paused"
            if paused and plan["applied"]
            else "pause_pending"
            if paused
            else "unknown"
            if not telemetry_available
            else "no_heartbeat"
            if collector_at is None
            else "configuration_pending"
            if (plan["managed"] or plan.get("controls_managed")) and not plan["applied"]
            else "request_failed"
            if error
            else "active"
            if state == "recent"
            else "delayed"
        )
        sources.append(
            CollectionSource(
                platform=platform,
                state=state,
                latest_observation=latest,
                delay_seconds=delay,
                total_markets=summary.get("total", 0),
                fresh_markets=summary.get("fresh", 0),
                collector_checked_at=collector_at,
                error_code=error,
                run_state=run_state,
                managed=plan["managed"],
                enabled_targets=counts.get(platform, 0) if plan["managed"] else None,
                desired_revision=plan["desired_revision"],
                applied_revision=plan["applied_revision"],
            )
        )
    return CollectionStatus(
        checked_at=now,
        sources=sources,
        analytics_checked_at=analytics_checked_at,
        analytics_state="active"
        if analytics_checked_at
        else "no_heartbeat"
        if telemetry_available
        else "unavailable",
    )
