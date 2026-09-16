from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema


class TopicCoverage(Schema):
    slug: str
    name: str
    name_zh: str
    description: str
    description_zh: str
    configured: int
    observed: int
    fresh: int
    price_usable: int
    volume_usable: int
    missing: int
    needs_attention: int
    checked_at: datetime


class TargetCoverage(Schema):
    id: UUID
    platform: str
    exchange_id: str
    label: str
    market_id: UUID | None
    state: Literal[
        "paused", "missing", "closed", "delayed", "warming", "ready", "limited", "blocked"
    ]
    last_observed_at: datetime | None
    price_usable: bool
    volume_usable: bool
    reasons: list[str]
