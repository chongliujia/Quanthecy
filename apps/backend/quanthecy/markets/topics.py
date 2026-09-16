from datetime import timedelta
from uuid import UUID

from django.http import Http404
from django.utils import timezone
from pydantic import ValidationError
from quanthecy_analytics.contracts.market import MarketObservation
from quanthecy_analytics.quality import research_quality

from .models import CollectionTarget, Market, ResearchTopic
from .selection import market_id
from .topic_schemas import TargetCoverage, TopicCoverage


def topic_market_ids(slug: str) -> list[UUID]:
    topic = ResearchTopic.objects.filter(slug=slug, enabled=True, is_public=True).first()
    if topic is None:
        raise Http404("Research topic not found")
    return [market_id(row.platform, row.exchange_id) for row in topic.targets.filter(enabled=True)]


def coverage(
    topics: list[ResearchTopic],
) -> tuple[list[TopicCoverage], dict[str, list[TargetCoverage]]]:
    at = timezone.now()
    targets = list(CollectionTarget.objects.filter(topic__in=topics).select_related("topic")[:1000])
    markets = Market.objects.in_bulk([market_id(row.platform, row.exchange_id) for row in targets])
    reports, details = [], {}
    for topic in topics:
        rows = []
        active_rows = []
        fresh = 0
        for target in targets:
            if target.topic_id != topic.pk:
                continue
            market = markets.get(market_id(target.platform, target.exchange_id))
            row = TargetCoverage(
                id=target.id,
                platform=target.platform,
                exchange_id=target.exchange_id,
                label=target.label,
                market_id=market.id if market else None,
                state="missing",
                last_observed_at=market.last_observed_at if market else None,
                price_usable=False,
                volume_usable=False,
                reasons=[],
            )
            if not topic.enabled or not target.enabled:
                row.state = "paused"
            elif market is not None:
                try:
                    latest = MarketObservation.model_validate(market.latest).model_dump(mode="json")
                    quality = research_quality(latest, market.metrics, at)
                    row.price_usable, row.volume_usable = (
                        quality.price_usable,
                        quality.volume_usable,
                    )
                    row.reasons = quality.reasons
                    row.state = quality.state
                except (ValidationError, ValueError, KeyError, TypeError):
                    row.state = "blocked"
                    row.reasons = ["invalid_stored_observation"]
                if market.status != "OPEN":
                    row.state = "closed"
                    row.price_usable = row.volume_usable = False
                elif not at - timedelta(seconds=180) <= market.last_observed_at <= at:
                    row.state = "delayed"
                    row.price_usable = row.volume_usable = False
                else:
                    fresh += 1
                    if (
                        row.state == "blocked"
                        and row.reasons
                        and set(row.reasons)
                        <= {"insufficient_history", "quality_not_evaluated", "analytics_pending"}
                    ):
                        row.state = "warming"
            rows.append(row)
            if topic.enabled and target.enabled:
                active_rows.append(row)
        reports.append(
            TopicCoverage(
                slug=topic.slug,
                name=topic.name,
                name_zh=topic.name_zh,
                description=topic.description,
                description_zh=topic.description_zh,
                configured=len(active_rows),
                observed=sum(row.market_id is not None for row in active_rows),
                fresh=fresh,
                price_usable=sum(row.price_usable for row in active_rows),
                volume_usable=sum(row.volume_usable for row in active_rows),
                missing=sum(row.state == "missing" for row in active_rows),
                needs_attention=sum(
                    row.state in {"missing", "closed", "delayed", "blocked"} for row in active_rows
                ),
                checked_at=at,
            )
        )
        details[topic.slug] = rows
    return reports, details


def public_topics() -> list[TopicCoverage]:
    return coverage(list(ResearchTopic.objects.filter(enabled=True, is_public=True)[:50]))[0]
