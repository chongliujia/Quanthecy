"""Operator-owned collection plan. PostgreSQL is authoritative; Redis is a delivery channel."""

import json
import re
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from redis import Redis

from quanthecy.accounts.models import User
from quanthecy.operations.console import tr
from quanthecy.operations.models import PlatformAuditLog

from .models import CollectionPlan, CollectionTarget, ResearchTopic

PLAN_ID = UUID(int=1)
SELECTION_KEY = "collector:selection:v1"
ACK_KEY = "collector:selection-status:v1"
PLATFORMS = ("polymarket", "kalshi")


def validate_exchange_id(platform: str, exchange_id: str) -> None:
    pattern = r"[0-9]{1,255}" if platform == "polymarket" else r"[A-Z0-9][A-Z0-9._-]{0,254}"
    if platform not in PLATFORMS or not re.fullmatch(pattern, exchange_id):
        raise ValidationError(
            {
                "exchange_id": tr(
                    "Use the exchange's exact market ID or ticker.",
                    "请填写交易所的市场 ID 或合约代码。",
                )
            }
        )


def market_id(platform: str, exchange_id: str) -> UUID:
    return uuid5(
        NAMESPACE_URL, f"https://quanthecy.org/identity/v1/{platform}/market/{exchange_id}"
    )


def lock_plan() -> CollectionPlan:
    """Call inside atomic; all operator mutations and publication share this lock."""
    CollectionPlan.objects.get_or_create(pk=PLAN_ID)
    return CollectionPlan.objects.select_for_update().get(pk=PLAN_ID)


def validate_candidate(candidate: ResearchTopic | CollectionTarget | None = None) -> None:
    topics = dict(ResearchTopic.objects.values_list("id", "enabled"))
    if isinstance(candidate, ResearchTopic):
        topics[candidate.pk] = candidate.enabled
    if len(topics) > 50:
        raise ValidationError(
            tr("At most 50 research topics are supported.", "最多支持 50 个研究主题。")
        )
    targets = list(
        CollectionTarget.objects.values(
            "id", "topic_id", "platform", "exchange_id", "enabled", "tier"
        )[:1001]
    )
    if isinstance(candidate, CollectionTarget):
        targets = [row for row in targets if row["id"] != candidate.pk]
        targets.append(
            {
                "id": candidate.id,
                "topic_id": candidate.topic_id,
                "platform": candidate.platform,
                "exchange_id": candidate.exchange_id,
                "enabled": candidate.enabled,
                "tier": candidate.tier,
            }
        )
    if len(targets) > 1000:
        raise ValidationError(
            tr(
                "At most 1,000 saved collection targets are supported.",
                "最多保存 1,000 条采集目标。",
            )
        )
    selected: dict[str, set[str]] = {platform: set() for platform in PLATFORMS}
    priority: dict[str, set[str]] = {platform: set() for platform in PLATFORMS}
    for row in targets:
        if row["enabled"] and topics.get(row["topic_id"]):
            validate_exchange_id(row["platform"], row["exchange_id"])
            selected[row["platform"]].add(row["exchange_id"])
            if row["tier"] == "priority":
                priority[row["platform"]].add(row["exchange_id"])
    if any(len(ids) > 50 for ids in priority.values()) or any(
        len(ids) > 250 for ids in selected.values()
    ):
        raise ValidationError(
            tr(
                "Each exchange allows 50 priority markets and 250 total targets. "
                "Pause or lower a tier first.",
                "每个交易所最多 50 个重点市场、250 个采集目标，请先暂停或降低采集层级。",
            )
        )


def record_change(
    plan: CollectionPlan, actor: User, subject_id: UUID, reason: str, details: dict[str, Any]
) -> None:
    plan.revision += 1
    plan.save(update_fields=["revision", "managed", "updated_at"])
    PlatformAuditLog.objects.create(
        actor=actor,
        action="collection.plan_changed",
        subject_id=subject_id,
        reason=reason,
        details={"revision": plan.revision, **details},
    )


def manifest(plan: CollectionPlan) -> dict[str, Any]:
    validate_candidate()
    universe: dict[str, list[str]] = {platform: [] for platform in PLATFORMS}
    intervals: dict[str, dict[str, int]] = {platform: {} for platform in PLATFORMS}
    targets = CollectionTarget.objects.filter(enabled=True, topic__enabled=True)
    tiered = plan.coverage_managed or targets.filter(tier="standard").exists()
    for target in targets.order_by("platform", "exchange_id"):
        interval = getattr(plan, f"{target.platform}_interval_seconds")
        if target.tier == "standard":
            interval = max(interval, plan.standard_interval_seconds)
        previous = intervals[target.platform].get(target.exchange_id, interval)
        intervals[target.platform][target.exchange_id] = min(previous, interval)
    for platform in PLATFORMS:
        universe[platform] = sorted(intervals[platform])
    return {
        "schema_version": 3 if tiered else 2 if plan.controls_managed else 1,
        "revision": plan.revision,
        "enabled": plan.managed,
        "universe": universe,
        **({"sources": source_controls(plan)} if plan.controls_managed or tiered else {}),
        **(
            {
                "intervals": intervals,
                "discovery": {
                    "enabled": plan.catalog_enabled,
                    "interval_seconds": plan.catalog_interval_seconds,
                    "page_interval_seconds": plan.catalog_page_interval_seconds,
                    "max_pages": plan.catalog_max_pages,
                },
            }
            if tiered
            else {}
        ),
    }


def source_controls(plan: CollectionPlan) -> dict[str, dict[str, Any]]:
    return {
        platform: {
            "enabled": getattr(plan, f"{platform}_enabled"),
            "interval_seconds": getattr(plan, f"{platform}_interval_seconds"),
        }
        for platform in PLATFORMS
    }


@transaction.atomic
def publish_selection() -> None:
    plan = lock_plan()
    if not plan.managed and not plan.controls_managed:
        return  # Uninitialized installs retain their existing collector discovery/configuration.
    payload = manifest(plan)
    with Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5
    ) as cache:
        cache.set(SELECTION_KEY, json.dumps(payload, separators=(",", ":")), ex=300)


def selection_status() -> dict[str, Any]:
    plan = CollectionPlan.objects.filter(pk=PLAN_ID).first()
    state: dict[str, Any] = {
        "managed": bool(plan and plan.managed),
        "controls_managed": bool(plan and plan.controls_managed),
        "sources": source_controls(plan) if plan and plan.controls_managed else {},
        "desired_revision": plan.revision if plan else None,
        "applied_revision": None,
        "checked_at": None,
        "applied": False,
    }
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
        ) as cache:
            raw = cache.get(ACK_KEY)
        if not isinstance(raw, (str, bytes)) or len(raw) > 4096:
            return state
        value = json.loads(raw)
        at = datetime.fromisoformat(value["checked_at"])
        if at.tzinfo is None or not 0 <= (timezone.now() - at).total_seconds() <= 180:
            return state
        if type(value["revision"]) is not int or value["revision"] < 1:
            return state
        state.update(applied_revision=value["revision"], checked_at=at)
        state["applied"] = bool(
            plan
            and (plan.managed or plan.controls_managed)
            and value.get("enabled") == plan.managed
            and value["revision"] == plan.revision
            and (not plan.controls_managed or value.get("schema_version") in (2, 3))
            and (not plan.coverage_managed or value.get("schema_version") == 3)
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    except Exception:
        pass  # Telemetry loss does not erase configured targets or persisted data.
    return state
