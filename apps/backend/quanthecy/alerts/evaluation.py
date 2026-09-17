"""Evaluate rules in the ingestion transaction, so checkpoints and notifications agree."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from quanthecy_analytics.alert_metrics import evaluate_window
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository

from quanthecy.watchlists.models import Watchlist, WatchlistItem

from .models import AlertCursor, AlertEvent, AlertRule


def evaluate_observation(repository: ClickHouseRepository, row: dict[str, Any]) -> int:
    candidates = list(
        AlertRule.objects.filter(
            enabled=True, watchlist__archived=False, watchlist__items__market_id=row["market"]["id"]
        ).values_list("id", "watchlist_id")
    )
    if not candidates:
        return 0
    end = datetime.fromisoformat(row["received_at"])
    cache: dict[tuple[int, str], dict[str, Any]] = {}
    emitted = 0
    for rule_id, list_id in candidates:
        with transaction.atomic():
            watchlist = Watchlist.objects.select_for_update().get(id=list_id)
            rule = AlertRule.objects.select_for_update().get(id=rule_id)
            item = WatchlistItem.objects.filter(
                watchlist=watchlist, market_id=row["market"]["id"]
            ).first()
            if (
                watchlist.archived
                or not rule.enabled
                or item is None
                or watchlist.organization_id != rule.organization_id
                or end < max(rule.effective_at, item.added_at)
            ):
                continue
            cursor, _ = AlertCursor.objects.get_or_create(rule=rule, market_id=row["market"]["id"])
            if cursor.revision != rule.revision:
                cursor.revision = rule.revision
                cursor.armed = True
            if cursor.last_observed_at is not None and end <= cursor.last_observed_at:
                continue
            key = (rule.window_minutes, rule.kind)
            if key not in cache:
                history = repository.history(
                    UUID(row["market"]["id"]),
                    start=(end - timedelta(minutes=rule.window_minutes + 3)).isoformat(),
                    end=end.isoformat(),
                    known_at=row["recorded_at"],
                    limit=1001,
                )
                cache[key] = evaluate_window(
                    history[:1000],
                    window_minutes=rule.window_minutes,
                    kind=rule.kind,
                    observation_id=row["observation_id"],
                    now=timezone.now(),
                    truncated=len(history) > 1000,
                )
            result = cache[key]
            cursor.last_observed_at = end
            cursor.last_observation_id = UUID(row["observation_id"])
            cursor.evaluated_at = timezone.now()
            cursor.value_pp = result["value_pp"]
            cursor.reason = result["reason"]
            if not result["eligible"]:
                cursor.status = "INELIGIBLE"
            else:
                value = Decimal(str(result["value_pp"]))
                magnitude = (
                    abs(value)
                    if rule.direction == "EITHER"
                    else -value
                    if rule.direction == "DOWN"
                    else value
                )
                matched = magnitude >= rule.threshold_pp
                cooling = bool(
                    cursor.last_triggered_at
                    and (end - cursor.last_triggered_at) < timedelta(minutes=rule.cooldown_minutes)
                )
                if not matched:
                    cursor.armed, cursor.status = True, "ARMED"
                elif not cursor.armed:
                    cursor.status = "LATCHED"
                elif cooling:
                    cursor.status = "COOLDOWN"
                else:
                    _, created = AlertEvent.objects.get_or_create(
                        organization_id=rule.organization_id,
                        rule=rule,
                        market_id=row["market"]["id"],
                        revision=rule.revision,
                        observation_id=row["observation_id"],
                        defaults={
                            "observed_at": end,
                            "snapshot": {
                                "title": row["market"]["title"],
                                "platform": row["platform"],
                                "outcome": row["outcome"],
                                "watchlist_name": watchlist.name,
                                "rule": {
                                    "name": rule.name,
                                    "kind": rule.kind,
                                    "direction": rule.direction,
                                    "threshold_pp": float(rule.threshold_pp),
                                    "window_minutes": rule.window_minutes,
                                    "cooldown_minutes": rule.cooldown_minutes,
                                    "revision": rule.revision,
                                },
                                "calculation": result,
                            },
                        },
                    )
                    cursor.armed, cursor.status = False, "TRIGGERED"
                    cursor.last_triggered_at = end
                    emitted += int(created)
            cursor.save()
    return emitted
