from datetime import datetime
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Query, Router

from quanthecy.markets.topic_schemas import TopicCoverage
from quanthecy.markets.topics import public_topics
from quanthecy.research import events, services
from quanthecy.research.event_schemas import EventDetail, EventSummary
from quanthecy.research.schemas import (
    ComparisonDetail,
    EvidenceDetail,
    EvidencePage,
    FeedSignal,
    ResearchOverview,
    ReviewOut,
    TimelineOut,
)

router = Router(tags=["Research"])


@router.get("/research/overview", response=ResearchOverview)
def overview(request: HttpRequest) -> ResearchOverview:
    return services.overview()


@router.get("/comparisons", response=list[ReviewOut])
def comparisons(request: HttpRequest, cutoff: datetime | None = None) -> list[ReviewOut]:
    return services.comparisons(cutoff)


@router.get("/comparisons/{pair_id}", response=ComparisonDetail)
def comparison(
    request: HttpRequest,
    pair_id: UUID,
    cutoff: datetime | None = None,
    hours: int = Query(24, ge=1, le=24),
) -> ComparisonDetail:
    return services.comparison_detail(pair_id, cutoff, hours)


@router.get("/evidence", response=EvidencePage)
def evidence(
    request: HttpRequest,
    cutoff: datetime | None = None,
    source: str = Query("", max_length=80),
    search: str = Query("", max_length=200),
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=100),
) -> EvidencePage:
    return services.evidence_list(cutoff, source, search, offset, limit)


@router.get("/evidence/{item_id}", response=EvidenceDetail)
def evidence_item(
    request: HttpRequest, item_id: UUID, cutoff: datetime | None = None
) -> EvidenceDetail:
    return services.evidence_detail(item_id, cutoff)


@router.get("/markets/{market_id}/timeline", response=TimelineOut)
def timeline(request: HttpRequest, market_id: UUID, cutoff: datetime | None = None) -> TimelineOut:
    return services.timeline(market_id, cutoff)


@router.get("/signals", response=list[FeedSignal])
def signals(
    request: HttpRequest,
    platform: Literal["polymarket", "kalshi"] | None = None,
    signal_type: Literal["PROBABILITY_SPIKE", "PROBABILITY_DROP", "SPREAD_WIDENING", "VOLUME_SPIKE"]
    | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[FeedSignal]:
    return services.signal_feed(platform, signal_type, limit)


@router.get("/research/topics", response=list[TopicCoverage])
def topics(request: HttpRequest) -> list[TopicCoverage]:
    return public_topics()


@router.get("/research/events", response=list[EventSummary])
def research_events(
    request: HttpRequest, cutoff: datetime | None = None, market_id: UUID | None = None
) -> list[EventSummary]:
    return events.event_list(cutoff, market_id)


@router.get("/research/events/{slug}", response=EventDetail)
def research_event(request: HttpRequest, slug: str, cutoff: datetime | None = None) -> EventDetail:
    return events.event_detail(slug, cutoff)
