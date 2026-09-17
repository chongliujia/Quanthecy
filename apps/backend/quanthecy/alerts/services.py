from typing import Any, Literal, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from quanthecy_analytics.quality import STALE_SECONDS

from quanthecy.accounts.models import User
from quanthecy.organizations.policies import require_org_member
from quanthecy.watchlists.services import get_list, require_writer

from .models import AlertEvent, AlertReceipt, AlertRule
from .schemas import EventDetail, EventOut, EventPage, RuleInput, RuleOut, RuleState


@transaction.atomic
def save_rule(
    actor: User,
    organization_id: UUID,
    list_id: UUID,
    payload: RuleInput,
    rule_id: UUID | None = None,
) -> UUID:
    require_writer(actor, organization_id)
    watchlist = get_list(organization_id, list_id, lock=True)
    values = payload.model_dump()
    values["name"] = payload.name.strip()
    if not values["name"]:
        raise ValidationError("Enter an alert name.")
    if payload.kind == "SPREAD_WIDENING":
        values["direction"] = "UP"
    if rule_id is None:
        if watchlist.alert_rules.count() >= 10:
            raise ValidationError("A watchlist supports at most 10 alert rules.")
        rule = AlertRule.objects.create(
            organization_id=organization_id, watchlist=watchlist, **values
        )
    else:
        rule = get_object_or_404(
            AlertRule.objects.select_for_update(),
            id=rule_id,
            organization_id=organization_id,
            watchlist=watchlist,
        )
        for field, value in values.items():
            setattr(rule, field, value)
        rule.revision += 1
        rule.effective_at = timezone.now()
        rule.save()
    return rule.id


def rules(actor: User, organization_id: UUID, list_id: UUID) -> list[RuleOut]:
    require_org_member(actor, organization_id)
    watchlist = get_list(organization_id, list_id)
    items = list(watchlist.items.select_related("market"))
    now = timezone.now()
    output = []
    for rule in watchlist.alert_rules.prefetch_related("cursors"):
        cursors = {cursor.market_id: cursor for cursor in rule.cursors.all()}
        states = []
        for item in items:
            cursor = cursors.get(item.market_id)
            current = bool(cursor and cursor.revision == rule.revision)
            status = cursor.status if cursor and current else "WAITING"
            reason = cursor.reason if cursor and current else "awaiting_new_observation"
            if not rule.enabled:
                status, reason = "PAUSED", "rule_disabled"
            elif item.market.status != "OPEN":
                status, reason = "INELIGIBLE", "market_not_open"
            elif not 0 <= (now - item.market.last_observed_at).total_seconds() <= STALE_SECONDS:
                status, reason = "INELIGIBLE", "stale_observation"
            states.append(
                RuleState(
                    market_id=item.market_id,
                    title=item.market.title,
                    status=status,
                    reason=reason,
                    value_pp=cursor.value_pp if cursor and current else None,
                    evaluated_at=cursor.evaluated_at if cursor and current else None,
                )
            )
        output.append(
            RuleOut(
                id=rule.id,
                watchlist_id=rule.watchlist_id,
                revision=rule.revision,
                name=rule.name,
                kind=cast(Literal["PROBABILITY_MOVE", "SPREAD_WIDENING"], rule.kind),
                direction=cast(Literal["EITHER", "UP", "DOWN"], rule.direction),
                threshold_pp=rule.threshold_pp,
                window_minutes=cast(Literal[5, 15, 60], rule.window_minutes),
                cooldown_minutes=rule.cooldown_minutes,
                enabled=rule.enabled,
                states=states,
            )
        )
    return output


def event_values(event: AlertEvent, is_read: bool) -> dict[str, Any]:
    saved = event.snapshot
    return {
        "id": event.id,
        "market_id": event.market_id,
        "title": saved["title"],
        "platform": saved["platform"],
        "rule_name": saved["rule"]["name"],
        "kind": saved["rule"]["kind"],
        "direction": saved["rule"]["direction"],
        "threshold_pp": saved["rule"]["threshold_pp"],
        "window_minutes": saved["rule"]["window_minutes"],
        "value_pp": saved["calculation"]["value_pp"],
        "revision": event.revision,
        "observed_at": event.observed_at,
        "created_at": event.created_at,
        "is_read": is_read,
    }


def events(
    actor: User,
    organization_id: UUID,
    *,
    offset: int,
    limit: int,
    unread_only: bool = False,
    market_id: UUID | None = None,
) -> EventPage:
    require_org_member(actor, organization_id)
    query = AlertEvent.objects.filter(organization_id=organization_id).annotate(
        is_read=Exists(AlertReceipt.objects.filter(event_id=OuterRef("pk"), user=actor))
    )
    if market_id:
        query = query.filter(market_id=market_id)
    unread = query.filter(is_read=False).count()
    if unread_only:
        query = query.filter(is_read=False)
    return EventPage(
        items=[
            EventOut(**event_values(event, event.is_read))
            for event in query[offset : offset + limit]
        ],
        total=query.count(),
        unread=unread,
        offset=offset,
        limit=limit,
    )


def event_detail(actor: User, organization_id: UUID, event_id: UUID) -> EventDetail:
    require_org_member(actor, organization_id)
    event = get_object_or_404(AlertEvent, id=event_id, organization_id=organization_id)
    return EventDetail(
        **event_values(event, event.receipts.filter(user=actor).exists()), snapshot=event.snapshot
    )


def mark_read(actor: User, organization_id: UUID, event_id: UUID, read: bool) -> None:
    # A viewer may update their own read receipt, never a shared rule or another user's receipt.
    require_org_member(actor, organization_id)
    event = get_object_or_404(AlertEvent, id=event_id, organization_id=organization_id)
    if read:
        AlertReceipt.objects.get_or_create(event=event, user=actor)
    else:
        AlertReceipt.objects.filter(event=event, user=actor).delete()
