from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import field_serializer

from .schemas import EvidenceOut


class EventSummary(Schema):
    id: UUID
    slug: str
    definition_id: UUID
    version: int
    title: str
    title_zh: str
    scope: str
    scope_zh: str
    starts_on: date
    ends_on: date
    calendar_url: str
    observed_at: datetime
    market_count: int


class EventContract(Schema):
    id: UUID
    platform: str
    title: str
    outcome: str
    resolution_rules: str
    closes_at: str | None
    linked_at: datetime


class EventChartPoint(Schema):
    at: datetime
    probability: float | None
    observed_at: datetime | None
    observation_id: UUID | None
    issue: Literal["missing", "stale", "invalid_quote", "contract_changed"] | None


class EventChartSeries(Schema):
    market_id: UUID
    points: list[EventChartPoint]
    truncated: bool


class EventChart(Schema):
    event: EventSummary
    start: datetime
    end: datetime
    step_seconds: int
    max_age_seconds: int
    contracts: list[EventContract]
    contracts_truncated: bool
    series: list[EventChartSeries]


class EventReviewOut(Schema):
    id: UUID
    relation: Literal["DIRECT", "BACKGROUND", "UNRELATED"]
    rationale: str
    paragraphs: list[int]
    reviewed_at: datetime
    feed_quote: str = ""
    stance: Literal["UNKNOWN", "SUPPORTS", "OPPOSES"] = "UNKNOWN"
    target_contract_id: UUID | None = None
    target_market_id: UUID | None = None
    target_snapshot: dict[str, Any] | None = None


class Passage(Schema):
    paragraph: int
    text: str
    truncated: bool = False


class EventEvidenceOut(Schema):
    id: UUID
    evidence: EvidenceOut
    status: Literal["PENDING", "STALE", "DIRECT", "BACKGROUND", "UNRELATED"]
    review: EventReviewOut | None
    passages: list[Passage]
    history: list[EventReviewOut]
    matched_at: datetime
    discovery: dict[str, Any] = {}
    changes: dict[str, Any] = {}


class EventChange(Schema):
    id: str
    kind: Literal["SCOPE", "EVIDENCE", "REVISION", "REVIEW", "MARKET"]
    title: str
    observed_at: datetime
    item_id: UUID | None = None
    evidence_observed_at: datetime | None = None

    @field_serializer("evidence_observed_at")
    def precise_evidence_time(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


class EventDetail(Schema):
    event: EventSummary
    cutoff: datetime
    markets: list[EventContract]
    evidence: list[EventEvidenceOut]
    changes: list[EventChange]
    counts: dict[str, int]
    truncated: bool
    official_direct_count: int = 0
