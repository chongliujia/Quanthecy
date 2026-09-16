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
        CollectionTarget.objects.values("id", "topic_id", "platform", "exchange_id", "enabled")[
            :1001
        ]
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
    for row in targets:
        if row["enabled"] and topics.get(row["topic_id"]):
            validate_exchange_id(row["platform"], row["exchange_id"])
            selected[row["platform"]].add(row["exchange_id"])
    if any(len(ids) > 50 for ids in selected.values()):
        raise ValidationError(
            tr(
                "Each exchange allows at most 50 enabled unique markets. Pause a target first.",
                "每个交易所最多启用 50 个不同市场，请先暂停其他采集目标。",
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
    for platform, exchange_id in (
        CollectionTarget.objects.filter(enabled=True, topic__enabled=True)
        .values_list("platform", "exchange_id")
        .order_by("platform", "exchange_id")
        .distinct()
    ):
        universe[platform].append(exchange_id)
    return {
        "schema_version": 1,
        "revision": plan.revision,
        "enabled": plan.managed,
        "universe": universe,
    }


@transaction.atomic
def publish_selection() -> None:
    plan = lock_plan()
    if not plan.managed:
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
            and plan.managed
            and value.get("enabled") is True
            and value["revision"] == plan.revision
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    except Exception:
        pass  # Telemetry loss does not erase configured targets or persisted data.
    return state
