from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Max, OuterRef, Q, QuerySet, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from quanthecy_analytics.comparisons import aligned_history

from quanthecy.markets.models import Market
from quanthecy.markets.repositories import history_repository

from .models import (
    Comparison,
    ComparisonReview,
    EvidenceLink,
    EvidenceRevision,
    EvidenceSource,
)
from .schemas import (
    ComparisonDetail,
    ComparisonPoint,
    EvidenceDetail,
    EvidenceOut,
    EvidencePage,
    FeedSignal,
    LinkOut,
    ResearchOverview,
    ReviewOut,
    SourceOut,
    TimelineEntry,
    TimelineOut,
)


def cutoff_time(value: datetime | None) -> datetime:
    now = timezone.now()
    if value is None:
        return now
    if value.tzinfo is None or value > now:
        raise ValidationError("Use a timezone-aware cutoff no later than now.")
    return value.astimezone(UTC)


def overview() -> ResearchOverview:
    now = timezone.now()
    return ResearchOverview(
        markets=Market.objects.count(),
        fresh_markets=Market.objects.filter(
            status="OPEN", last_observed_at__gte=now - timedelta(seconds=180)
        ).count(),
        reviewed_pairs=Comparison.objects.filter(reviews__isnull=False).distinct().count(),
        evidence_items=visible_evidence(now).count(),
        latest_observation=Market.objects.aggregate(value=Max("last_observed_at"))["value"],
        sources=[SourceOut.from_orm(source) for source in EvidenceSource.objects.order_by("slug")],
        news_polling_enabled=settings.NEWS_FEEDS_ENABLED,
    )


def comparisons(cutoff: datetime | None) -> list[ReviewOut]:
    at = cutoff_time(cutoff)
    latest = (
        ComparisonReview.objects.filter(
            comparison_id=OuterRef("comparison_id"), reviewed_at__lte=at
        )
        .order_by("-version")
        .values("id")[:1]
    )
    return [
        ReviewOut.from_orm(review)
        for review in ComparisonReview.objects.filter(id=Subquery(latest)).order_by("title", "id")[
            :100
        ]
    ]


def comparison_detail(pair_id: UUID, cutoff: datetime | None, hours: int) -> ComparisonDetail:
    at = cutoff_time(cutoff)
    pair = get_object_or_404(Comparison, pk=pair_id, created_at__lte=at)
    reviews = list(pair.reviews.filter(reviewed_at__lte=at).order_by("version"))
    if not reviews:
        raise Http404("No comparison review was available at this cutoff.")
    repository = history_repository()
    start = at - timedelta(hours=hours)
    rows = [
        repository.history(
            market,
            start=(start - timedelta(seconds=180)).isoformat(),
            end=at.isoformat(),
            limit=10001,
        )
        for market in (pair.left_id, pair.right_id)
    ]
    if any(len(side) > 10000 for side in rows):
        raise ValidationError("Comparison exceeds 10,000 inputs per side. Choose a shorter window.")
    times = [start + timedelta(minutes=5 * i) for i in range(hours * 12 + 1)]
    points = aligned_history(
        rows[0],
        rows[1],
        [
            dict(
                version=r.version,
                reviewed_at=r.reviewed_at,
                relation=r.relation,
                alignment=r.alignment,
                left_snapshot=r.left_snapshot,
                right_snapshot=r.right_snapshot,
            )
            for r in reviews
        ],
        times,
    )
    return ComparisonDetail(
        review=ReviewOut.from_orm(reviews[-1]),
        revisions=[ReviewOut.from_orm(r) for r in reviews],
        cutoff=at,
        current=ComparisonPoint(**points[-1]),
        history=[ComparisonPoint(**point) for point in points],
    )


def visible_evidence(at: datetime) -> QuerySet[EvidenceRevision]:
    latest = (
        EvidenceRevision.objects.filter(item_id=OuterRef("item_id"), observed_at__lte=at)
        .order_by("-version")
        .values("id")[:1]
    )
    return (
        EvidenceRevision.objects.filter(id=Subquery(latest))
        .filter(Q(published_at__isnull=True) | Q(published_at__lte=at))
        .select_related("item__source")
    )


def evidence_value(revision: EvidenceRevision) -> EvidenceOut:
    return EvidenceOut(
        id=revision.item_id,
        revision_id=revision.id,
        version=revision.version,
        source_slug=revision.item.source_id,
        source_name=revision.item.source.name,
        title=revision.title,
        excerpt=revision.excerpt,
        url=revision.url,
        published_at=revision.published_at,
        first_observed_at=revision.item.first_observed_at,
        observed_at=revision.observed_at,
        content_hash=revision.content_hash,
    )


def evidence_list(
    cutoff: datetime | None, source: str, search: str, offset: int, limit: int
) -> EvidencePage:
    at = cutoff_time(cutoff)
    query = visible_evidence(at)
    if source:
        query = query.filter(item__source_id=source)
    if search:
        query = query.filter(Q(title__icontains=search) | Q(excerpt__icontains=search))
    return EvidencePage(
        items=[
            evidence_value(r)
            for r in query.order_by("-published_at", "-observed_at", "id")[offset : offset + limit]
        ],
        total=query.count(),
        cutoff=at,
    )


def evidence_detail(item_id: UUID, cutoff: datetime | None) -> EvidenceDetail:
    at = cutoff_time(cutoff)
    current = get_object_or_404(visible_evidence(at), item_id=item_id)
    latest_link = (
        EvidenceLink.objects.filter(
            item_id=item_id, market_id=OuterRef("market_id"), created_at__lte=at
        )
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    links = EvidenceLink.objects.filter(item_id=item_id, id=Subquery(latest_link)).order_by(
        "market_id"
    )
    revisions = (
        EvidenceRevision.objects.filter(item_id=item_id, observed_at__lte=at)
        .filter(Q(published_at__isnull=True) | Q(published_at__lte=at))
        .select_related("item__source")
        .order_by("-version")
    )
    return EvidenceDetail(
        item=evidence_value(current),
        revisions=[evidence_value(r) for r in revisions[:100]],
        links=[LinkOut.from_orm(link) for link in links[:100]],
        cutoff=at,
    )


def timeline(market_id: UUID, cutoff: datetime | None) -> TimelineOut:
    at = cutoff_time(cutoff)
    get_object_or_404(Market, pk=market_id, first_observed_at__lte=at)
    latest_link = (
        EvidenceLink.objects.filter(
            market_id=market_id, item_id=OuterRef("item_id"), created_at__lte=at
        )
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    links = list(
        EvidenceLink.objects.filter(market_id=market_id, id=Subquery(latest_link))
        .exclude(status=EvidenceLink.Status.REJECTED)
        .filter(item_id__in=visible_evidence(at).values("item_id"))
        .order_by("-created_at", "id")[:101]
    )
    evidence = {
        r.item_id: evidence_value(r)
        for r in visible_evidence(at).filter(item_id__in=[link.item_id for link in links[:100]])
    }
    items = [
        TimelineEntry(evidence=evidence[link.item_id], association=LinkOut.from_orm(link))
        for link in links[:100]
    ]
    items.sort(
        key=lambda item: (
            item.evidence.published_at or item.evidence.observed_at,
            str(item.evidence.id),
        ),
        reverse=True,
    )
    return TimelineOut(items=items, cutoff=at, truncated=len(links) > 100)


def signal_feed(platform: str | None, signal_type: str | None, limit: int) -> list[FeedSignal]:
    rows = history_repository().recent_signals(
        platform=platform, signal_type=signal_type, limit=limit
    )
    markets = Market.objects.in_bulk([r["market_id"] for r in rows])
    return [
        FeedSignal(
            **row,
            market_title=markets[UUID(row["market_id"])].title,
            platform=markets[UUID(row["market_id"])].platform,
        )
        for row in rows
        if UUID(row["market_id"]) in markets
    ]
