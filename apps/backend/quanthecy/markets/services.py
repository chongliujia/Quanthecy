from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F
from django.db.models.functions import Abs
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from quanthecy_analytics.contracts.market import MarketObservation
from quanthecy_analytics.contracts.validation import validate_observation
from quanthecy_analytics.exports import export_observations
from quanthecy_analytics.quality import STALE_SECONDS
from quanthecy_analytics.quality import VERSION as QUALITY_VERSION
from quanthecy_analytics.signals import analyze
from redis import Redis

from .models import Market
from .repositories import history_repository
from .schemas import HistoryPage, MarketDetail, MarketPage, MarketSummary, SignalOut, summary_values


def list_markets(
    *,
    platform: str | None,
    search: str,
    sort: str,
    offset: int,
    limit: int,
    topic: str = "",
    market_ids: list[UUID] | None = None,
) -> MarketPage:
    query = Market.objects.all()
    if market_ids is not None:
        query = query.filter(id__in=market_ids)
    if topic:
        from .topics import topic_market_ids

        query = query.filter(id__in=topic_market_ids(topic))
    if platform:
        query = query.filter(platform=platform)
    if search:
        query = query.filter(title__icontains=search)
    if sort in ("movement", "volume_anomaly"):
        query = query.filter(
            status="OPEN",
            last_observed_at__gte=timezone.now() - timedelta(seconds=STALE_SECONDS),
            last_observed_at__lte=timezone.now(),
            metrics__quality__version=QUALITY_VERSION,
        )
        if sort == "movement":
            query = query.filter(
                probability_change_15m__isnull=False, metrics__quality__price_usable=True
            ).order_by(Abs("probability_change_15m").desc(), "id")
        else:
            query = query.filter(
                volume_zscore__isnull=False, metrics__quality__volume_usable=True
            ).order_by(F("volume_zscore").desc(), "id")
    else:
        query = query.order_by("-last_observed_at", "id")
    total = query.count()
    items = [
        MarketSummary(
            **summary_values(
                m,
                (timezone.now() - m.last_observed_at).total_seconds() > STALE_SECONDS,
                timezone.now(),
            )
        )
        for m in query[offset : offset + limit]
    ]
    return MarketPage(items=items, total=total, offset=offset, limit=limit)


def market_detail(market_id: UUID, cutoff: datetime | None = None) -> MarketDetail:
    market = get_object_or_404(Market, id=market_id)
    if cutoff is not None:
        from quanthecy.research.services import cutoff_time

        at = cutoff_time(cutoff)
        if at < market.first_observed_at:
            raise Http404("No observations available at this cutoff.")
        repository = history_repository()
        rows = repository.history(
            market_id,
            start=market.first_observed_at.isoformat(),
            end=at.isoformat(),
            known_at=at.isoformat(),
            limit=1,
            descending=True,
        )
        if not rows:
            raise Http404("No observations available at this cutoff.")
        market.latest = rows[0]
        market.title = rows[0]["market"]["title"]
        market.status = rows[0]["market"]["status"]
        market.last_observed_at = datetime.fromisoformat(rows[0]["received_at"])
        inputs = repository.history(
            market_id,
            start=(market.last_observed_at - timedelta(minutes=20)).isoformat(),
            end=at.isoformat(),
            known_at=at.isoformat(),
            limit=1001,
        )
        market.metrics = analyze(inputs[:1000], truncated=len(inputs) > 1000)[0]
        return MarketDetail(
            **summary_values(
                market, (at - market.last_observed_at).total_seconds() > STALE_SECONDS, at
            ),
            latest=market.latest,
            live_cache=False,
        )
    cached = False
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1
        ) as redis:
            raw = redis.get(f"market:{market.platform}:{market.id}")
        if isinstance(raw, (str, bytes)):
            value = validate_observation(raw).model_dump(mode="json")
            observed = datetime.fromisoformat(value["received_at"])
            if (
                value["market"]["id"] == str(market.id)
                and market.last_observed_at <= observed <= timezone.now()
            ):
                market.latest = value
                market.status = value["market"]["status"]
                market.title = value["market"]["title"]
                market.last_observed_at = observed
                cached = True
    except Exception:
        pass  # Cache loss cannot hide persisted metadata/history.
    stale = (timezone.now() - market.last_observed_at).total_seconds() > STALE_SECONDS
    return MarketDetail(
        **summary_values(market, stale, timezone.now()), latest=market.latest, live_cache=cached
    )


def window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = end or timezone.now()
    start = start or end - timedelta(days=1)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationError("Use timezone-aware timestamps, such as 2026-09-15T00:00:00Z.")
    if start >= end or end - start > timedelta(days=7):
        raise ValidationError("Choose an increasing window of at most seven days.")
    return start.astimezone(UTC), end.astimezone(UTC)


def market_history(
    market_id: UUID, start: datetime | None, end: datetime | None, limit: int
) -> HistoryPage:
    get_object_or_404(Market, id=market_id)
    start, end = window(start, end)
    rows = history_repository().history(
        market_id,
        start=start.isoformat(),
        end=end.isoformat(),
        known_at=end.isoformat(),
        limit=limit + 1,
    )
    return HistoryPage(
        items=[MarketObservation.model_validate(row) for row in rows[:limit]],
        start=start,
        end=end,
        truncated=len(rows) > limit,
    )


def market_signals(market_id: UUID, cutoff: datetime | None = None) -> list[SignalOut]:
    get_object_or_404(Market, id=market_id)
    if cutoff is None:
        return [SignalOut(**s) for s in history_repository().signals(market_id)]
    from quanthecy.research.services import cutoff_time

    at = cutoff_time(cutoff)
    repository = history_repository()
    candidates = repository.signals(market_id, cutoff=at.isoformat())
    visible = []
    for signal in candidates:
        inputs = repository.signal_inputs(signal)
        if {row["observation_id"] for row in inputs} == set(signal["observation_ids"]) and all(
            datetime.fromisoformat(row["recorded_at"]) <= at for row in inputs
        ):
            visible.append(SignalOut(**signal))
    return visible


def export_history(
    market_id: UUID,
    start: datetime | None,
    end: datetime | None,
    file_format: Literal["csv", "parquet"],
) -> bytes:
    page = market_history(market_id, start, end, 10000)
    if page.truncated:
        raise ValidationError("Export exceeds 10,000 observations. Choose a shorter time window.")
    return export_observations([row.model_dump(mode="json") for row in page.items], file_format)


def export_signal(signal_id: UUID, file_format: Literal["csv", "parquet"]) -> bytes:
    repository = history_repository()
    signal = repository.signal(signal_id)
    if signal is None:
        raise Http404("Signal not found")
    rows = repository.signal_inputs(signal)
    if {r["observation_id"] for r in rows} != set(signal["observation_ids"]):
        raise ValidationError("Some signal inputs are unavailable; export would be incomplete.")
    return export_observations(rows, file_format)
