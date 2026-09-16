from datetime import date, datetime
from typing import Literal
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


class EventReviewOut(Schema):
    id: UUID
    relation: Literal["DIRECT", "BACKGROUND", "UNRELATED"]
    rationale: str
    paragraphs: list[int]
    reviewed_at: datetime


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
