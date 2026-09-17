from uuid import UUID

from django.http import HttpRequest
from ninja import Query, Router

from quanthecy.alerts import services as alerts
from quanthecy.alerts.schemas import EventDetail, EventPage, ReadInput, RuleInput, RuleOut
from quanthecy.watchlists import services
from quanthecy.watchlists.schemas import (
    ItemInput,
    OrderInput,
    WatchlistDetail,
    WatchlistInput,
    WatchlistOut,
)

from .auth import current_user
from .schemas import Message

router = Router(tags=["Watchlists and alerts"])


@router.get("/{organization_id}/watchlists", response=list[WatchlistOut])
def watchlists(request: HttpRequest, organization_id: UUID) -> list[WatchlistOut]:
    return services.list_watchlists(current_user(request), organization_id)


@router.post("/{organization_id}/watchlists", response=WatchlistDetail)
def create(request: HttpRequest, organization_id: UUID, payload: WatchlistInput) -> WatchlistDetail:
    actor = current_user(request)
    list_id = services.save_list(actor, organization_id, payload.name)
    return services.detail(actor, organization_id, list_id)


@router.get("/{organization_id}/watchlists/{list_id}", response=WatchlistDetail)
def detail(request: HttpRequest, organization_id: UUID, list_id: UUID) -> WatchlistDetail:
    return services.detail(current_user(request), organization_id, list_id)


@router.patch("/{organization_id}/watchlists/{list_id}", response=WatchlistDetail)
def rename(
    request: HttpRequest, organization_id: UUID, list_id: UUID, payload: WatchlistInput
) -> WatchlistDetail:
    actor = current_user(request)
    services.save_list(actor, organization_id, payload.name, list_id)
    return services.detail(actor, organization_id, list_id)


@router.delete("/{organization_id}/watchlists/{list_id}", response=Message)
def archive(request: HttpRequest, organization_id: UUID, list_id: UUID) -> Message:
    services.archive_list(current_user(request), organization_id, list_id)
    return Message(detail="Watchlist archived; its rules are paused. Alert history is retained.")


@router.post("/{organization_id}/watchlists/{list_id}/items", response=Message)
def add(request: HttpRequest, organization_id: UUID, list_id: UUID, payload: ItemInput) -> Message:
    services.add_item(current_user(request), organization_id, list_id, payload.market_id)
    return Message(detail="Market added to watchlist.")


@router.delete("/{organization_id}/watchlists/{list_id}/items/{market_id}", response=Message)
def remove(request: HttpRequest, organization_id: UUID, list_id: UUID, market_id: UUID) -> Message:
    services.remove_item(current_user(request), organization_id, list_id, market_id)
    return Message(detail="Market removed from watchlist.")


@router.put("/{organization_id}/watchlists/{list_id}/order", response=Message)
def reorder(
    request: HttpRequest, organization_id: UUID, list_id: UUID, payload: OrderInput
) -> Message:
    services.reorder(current_user(request), organization_id, list_id, payload.market_ids)
    return Message(detail="Watchlist order saved.")


@router.get("/{organization_id}/watchlists/{list_id}/rules", response=list[RuleOut])
def rules(request: HttpRequest, organization_id: UUID, list_id: UUID) -> list[RuleOut]:
    return alerts.rules(current_user(request), organization_id, list_id)


@router.post("/{organization_id}/watchlists/{list_id}/rules", response=list[RuleOut])
def create_rule(
    request: HttpRequest, organization_id: UUID, list_id: UUID, payload: RuleInput
) -> list[RuleOut]:
    actor = current_user(request)
    alerts.save_rule(actor, organization_id, list_id, payload)
    return alerts.rules(actor, organization_id, list_id)


@router.put("/{organization_id}/watchlists/{list_id}/rules/{rule_id}", response=list[RuleOut])
def edit_rule(
    request: HttpRequest, organization_id: UUID, list_id: UUID, rule_id: UUID, payload: RuleInput
) -> list[RuleOut]:
    actor = current_user(request)
    alerts.save_rule(actor, organization_id, list_id, payload, rule_id)
    return alerts.rules(actor, organization_id, list_id)


@router.get("/{organization_id}/alerts", response=EventPage)
def inbox(
    request: HttpRequest,
    organization_id: UUID,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(30, ge=1, le=100),
    unread_only: bool = False,
    market_id: UUID | None = None,
) -> EventPage:
    return alerts.events(
        current_user(request),
        organization_id,
        offset=offset,
        limit=limit,
        unread_only=unread_only,
        market_id=market_id,
    )


@router.get("/{organization_id}/alerts/{event_id}", response=EventDetail)
def event(request: HttpRequest, organization_id: UUID, event_id: UUID) -> EventDetail:
    return alerts.event_detail(current_user(request), organization_id, event_id)


@router.patch("/{organization_id}/alerts/{event_id}/read", response=Message)
def read(
    request: HttpRequest, organization_id: UUID, event_id: UUID, payload: ReadInput
) -> Message:
    alerts.mark_read(current_user(request), organization_id, event_id, payload.read)
    return Message(detail="Read status saved.")
