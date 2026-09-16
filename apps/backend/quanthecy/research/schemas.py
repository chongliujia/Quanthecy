from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field
from quanthecy_analytics.contracts.market import Market as ContractMarket
from quanthecy_analytics.contracts.market import Outcome as ContractOutcome

from quanthecy.markets.schemas import SignalOut


class SourceOut(Schema):
    slug: str
    name: str
    url: str
    last_checked_at: datetime | None
    last_success_at: datetime | None
    error: str


class FrozenMarket(Schema):
    platform: str
    exchange_id: str
    market: ContractMarket
    outcome: ContractOutcome
    source: str
    observation_id: UUID


class ReviewOut(Schema):
    id: UUID
    comparison_id: UUID
    version: int
    title: str
    topic: str
    relation: Literal["EQUIVALENT", "RELATED", "INCOMPATIBLE"]
    alignment: Literal["SAME", "COMPLEMENT"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    differences: str
    reviewer_label: str
    reviewed_at: datetime
    left_snapshot: FrozenMarket
    right_snapshot: FrozenMarket


class QuoteOut(Schema):
    observation_id: UUID
    received_at: datetime
    recorded_at: datetime
    probability: float | None
    bid: float | None
    ask: float | None
    basis: str | None
    source: str | None
    quality_flags: list[str]


class ComparisonPoint(Schema):
    at: datetime
    left: QuoteOut | None
    right: QuoteOut | None
    difference: float | None
    skew_seconds: float | None
    issues: list[str]
    review_version: int | None


class ComparisonDetail(Schema):
    review: ReviewOut
    revisions: list[ReviewOut]
    cutoff: datetime
    current: ComparisonPoint
    history: list[ComparisonPoint]
    max_age_seconds: int = 180
    max_skew_seconds: int = 90


class EvidenceOut(Schema):
    id: UUID
    revision_id: UUID
    version: int
    source_slug: str
    source_name: str
    title: str
    excerpt: str
    url: str
    published_at: datetime | None
    first_observed_at: datetime
    observed_at: datetime
    content_hash: str


class EvidencePage(Schema):
    items: list[EvidenceOut]
    total: int
    cutoff: datetime


class LinkOut(Schema):
    id: UUID
    market_id: UUID
    status: Literal["TOPIC_ONLY", "REVIEWED", "REJECTED"]
    rationale: str
    method: str
    created_at: datetime


class EvidenceDetail(Schema):
    item: EvidenceOut
    revisions: list[EvidenceOut]
    links: list[LinkOut]
    cutoff: datetime


class TimelineEntry(Schema):
    evidence: EvidenceOut
    association: LinkOut


class TimelineOut(Schema):
    items: list[TimelineEntry]
    cutoff: datetime
    truncated: bool


class ResearchOverview(Schema):
    markets: int
    fresh_markets: int
    reviewed_pairs: int
    evidence_items: int
    latest_observation: datetime | None
    sources: list[SourceOut]
    news_polling_enabled: bool


class FeedSignal(SignalOut):
    market_title: str
    platform: str
