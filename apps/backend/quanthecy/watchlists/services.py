from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from quanthecy_analytics.quality import STALE_SECONDS

from quanthecy.accounts.models import User
from quanthecy.markets.models import Market
from quanthecy.markets.schemas import MarketSummary, summary_values
from quanthecy.organizations.models import Organization, OrganizationMembership
from quanthecy.organizations.policies import require_org_member, require_org_role

from .models import Watchlist, WatchlistItem
from .schemas import WatchlistDetail, WatchlistMarket, WatchlistOut

WRITE_ROLES: set[str] = {
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.ADMIN,
    OrganizationMembership.Role.MEMBER,
}


def require_writer(actor: User, organization_id: UUID) -> None:
    require_org_role(actor, organization_id, WRITE_ROLES)


def get_list(organization_id: UUID, list_id: UUID, *, lock: bool = False) -> Watchlist:
    query = Watchlist.objects.select_for_update() if lock else Watchlist.objects.all()
    return get_object_or_404(query, id=list_id, organization_id=organization_id, archived=False)


def list_watchlists(actor: User, organization_id: UUID) -> list[WatchlistOut]:
    require_org_member(actor, organization_id)
    return [
        WatchlistOut(id=w.id, name=w.name, count=w.count)
        for w in Watchlist.objects.filter(organization_id=organization_id, archived=False).annotate(
            count=Count("items")
        )
    ]


def detail(actor: User, organization_id: UUID, list_id: UUID) -> WatchlistDetail:
    require_org_member(actor, organization_id)
    watchlist = get_list(organization_id, list_id)
    now = timezone.now()
    items = [
        WatchlistMarket(
            position=item.position,
            market=MarketSummary(
                **summary_values(
                    item.market,
                    not 0 <= (now - item.market.last_observed_at).total_seconds() <= STALE_SECONDS,
                    now,
                )
            ),
        )
        for item in watchlist.items.select_related("market").all()
    ]
    return WatchlistDetail(id=watchlist.id, name=watchlist.name, count=len(items), items=items)


@transaction.atomic
def save_list(actor: User, organization_id: UUID, name: str, list_id: UUID | None = None) -> UUID:
    require_writer(actor, organization_id)
    Organization.objects.select_for_update().get(id=organization_id)
    name = name.strip()
    if not name or len(name) > 80:
        raise ValidationError("Use a watchlist name of 1–80 characters.")
    query = Watchlist.objects.filter(organization_id=organization_id, archived=False)
    duplicates = query.filter(name__iexact=name)
    if list_id is not None:
        duplicates = duplicates.exclude(id=list_id)
    if duplicates.exists():
        raise ValidationError("A watchlist with this name already exists.")
    if list_id is None:
        if query.count() >= 20:
            raise ValidationError("A workspace supports at most 20 active watchlists.")
        return Watchlist.objects.create(organization_id=organization_id, name=name).id
    watchlist = get_list(organization_id, list_id, lock=True)
    watchlist.name = name
    watchlist.save(update_fields=["name"])
    return watchlist.id


@transaction.atomic
def archive_list(actor: User, organization_id: UUID, list_id: UUID) -> None:
    require_writer(actor, organization_id)
    watchlist = get_list(organization_id, list_id, lock=True)
    watchlist.archived = True
    watchlist.save(update_fields=["archived"])
    watchlist.alert_rules.update(enabled=False)


@transaction.atomic
def add_item(actor: User, organization_id: UUID, list_id: UUID, market_id: UUID) -> None:
    require_writer(actor, organization_id)
    watchlist = get_list(organization_id, list_id, lock=True)
    market = get_object_or_404(Market, id=market_id)
    if watchlist.items.filter(market=market).exists():
        return
    if watchlist.items.count() >= 100:
        raise ValidationError("A watchlist supports at most 100 markets.")
    position = (watchlist.items.aggregate(last=Max("position"))["last"] or 0) + 1
    WatchlistItem.objects.create(watchlist=watchlist, market=market, position=position)


@transaction.atomic
def remove_item(actor: User, organization_id: UUID, list_id: UUID, market_id: UUID) -> None:
    require_writer(actor, organization_id)
    watchlist = get_list(organization_id, list_id, lock=True)
    watchlist.items.filter(market_id=market_id).delete()
    # Re-adding a market begins a new evaluation lifecycle; historical alerts survive.
    from quanthecy.alerts.models import AlertCursor

    AlertCursor.objects.filter(rule__watchlist=watchlist, market_id=market_id).delete()


@transaction.atomic
def reorder(actor: User, organization_id: UUID, list_id: UUID, market_ids: list[UUID]) -> None:
    require_writer(actor, organization_id)
    watchlist = get_list(organization_id, list_id, lock=True)
    items = {item.market_id: item for item in watchlist.items.all()}
    if len(market_ids) != len(set(market_ids)) or set(market_ids) != set(items):
        raise ValidationError("Reorder must include every current market exactly once.")
    for position, market_id in enumerate(market_ids):
        items[market_id].position = position
    WatchlistItem.objects.bulk_update(items.values(), ["position"])
