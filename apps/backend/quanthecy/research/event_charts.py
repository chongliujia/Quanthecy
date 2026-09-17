from datetime import datetime, timedelta
from uuid import UUID

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from quanthecy_analytics.event_chart import MAX_AGE_SECONDS, STEP_SECONDS, align_contract

from quanthecy.markets.repositories import history_repository

from .event_schemas import EventChart, EventChartPoint, EventChartSeries, EventContract
from .events import contract_matches, definitions, summary
from .models import EventMarketLink
from .services import cutoff_time

MAX_SERIES = 6
MAX_ROWS = 3000


def event_chart(
    slug: str, cutoff: datetime | None, hours: int, platform: str, market_ids: str
) -> EventChart:
    at = cutoff_time(cutoff)
    definition = get_object_or_404(definitions(at), event__slug=slug)
    try:
        requested = [UUID(value) for value in market_ids.split(",")] if market_ids else []
    except ValueError as exc:
        raise ValidationError("Use comma-separated market UUIDs.") from exc
    if len(requested) > MAX_SERIES or len(set(requested)) != len(requested):
        raise ValidationError("Choose up to six distinct linked contracts.")
    query = EventMarketLink.objects.filter(event=definition.event, created_at__lte=at)
    if platform:
        query = query.filter(snapshot__platform=platform)
    links = list(query.order_by("created_at", "id")[:101])
    truncated = len(links) > 100
    links = links[:100]
    available = {link.market_id: link for link in links}
    if not set(requested).issubset(available):
        raise ValidationError("Choose contracts from this event and platform at this cutoff.")
    selected = [available[key] for key in requested] if requested else links[:MAX_SERIES]
    contracts = [
        EventContract(
            id=link.market_id,
            platform=link.snapshot["platform"],
            title=link.snapshot["market"]["title"],
            outcome=link.snapshot["outcome"]["label"],
            resolution_rules=link.snapshot["market"]["resolution_rules"],
            closes_at=link.snapshot["market"].get("closes_at"),
            linked_at=link.created_at,
        )
        for link in links
    ]
    start = at - timedelta(hours=hours)
    repository = history_repository()
    series = []
    for link in selected:
        rows = repository.history(
            link.market_id,
            start=(start - timedelta(seconds=MAX_AGE_SECONDS)).isoformat(),
            end=at.isoformat(),
            known_at=at.isoformat(),
            limit=MAX_ROWS + 1,
            descending=True,
        )
        prepared = [
            dict(row, contract_changed=not contract_matches(link.snapshot, row))
            for row in rows[:MAX_ROWS]
        ]
        series.append(
            EventChartSeries(
                market_id=link.market_id,
                points=[
                    EventChartPoint.model_validate(point)
                    for point in align_contract(prepared, start=start, end=at)
                ],
                truncated=len(rows) > MAX_ROWS,
            )
        )
    return EventChart(
        event=summary(definition, at),
        start=start,
        end=at,
        contracts=contracts,
        contracts_truncated=truncated,
        series=series,
        step_seconds=STEP_SECONDS,
        max_age_seconds=MAX_AGE_SECONDS,
    )
