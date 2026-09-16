"""Version-bound event research. Matching is discovery, operator review is evidence."""

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .documents import OfficialDocument
from .event_schemas import (
    EventChange,
    EventContract,
    EventDetail,
    EventEvidenceOut,
    EventReviewOut,
    EventSummary,
    Passage,
)
from .feeds import SOURCES
from .models import (
    EventDefinition,
    EventEvidence,
    EventEvidenceReview,
    EventMarketLink,
    EvidenceItem,
    EvidenceRevision,
    ResearchEvent,
)
from .services import cutoff_time, evidence_value, visible_evidence


def definitions(at: datetime) -> QuerySet[EventDefinition]:
    latest = (
        EventDefinition.objects.filter(event_id=OuterRef("event_id"), observed_at__lte=at)
        .order_by("-version")
        .values("id")[:1]
    )
    return EventDefinition.objects.filter(
        id=Subquery(latest), event__created_at__lte=at, event__topic__is_public=True
    ).select_related("event")


@transaction.atomic
def append_definition(value: EventDefinition) -> None:
    ResearchEvent.objects.select_for_update().get(pk=value.event_id)
    previous = EventDefinition.objects.filter(event_id=value.event_id).order_by("-version").first()
    value.version = previous.version + 1 if previous else 1
    value.observed_at = timezone.now()
    if (
        not isinstance(value.source_slugs, list)
        or not 1 <= len(value.source_slugs) <= 10
        or any(not isinstance(s, str) or s not in SOURCES for s in value.source_slugs)
    ):
        raise ValidationError("Choose 1–10 official feed IDs.")
    value.full_clean()
    value.save()


def sync_event_candidates() -> int:
    """Bounded, idempotent discovery. Never copies an old version's human review."""
    now = timezone.now()
    created = 0
    for definition in definitions(now).order_by("event_id")[:20]:
        revisions = (
            visible_evidence(now)
            .filter(item__source_id__in=definition.source_slugs)
            .exclude(eventevidence__definition=definition)
            .order_by("-observed_at")[:100]
        )
        for revision in revisions:
            _, added = EventEvidence.objects.get_or_create(definition=definition, revision=revision)
            created += int(added)
    return created


def validate_review(value: EventEvidenceReview, *, lock: bool = False) -> None:
    candidate = value.candidate
    if lock:
        ResearchEvent.objects.select_for_update().get(pk=candidate.definition.event_id)
        EvidenceItem.objects.select_for_update().get(pk=candidate.revision.item_id)
        EventEvidence.objects.select_for_update().get(pk=candidate.pk)
    current_definition = (
        EventDefinition.objects.filter(event_id=candidate.definition.event_id)
        .order_by("-version")
        .first()
    )
    current_revision = (
        EvidenceRevision.objects.filter(item_id=candidate.revision.item_id)
        .order_by("-version")
        .first()
    )
    if current_definition != candidate.definition or current_revision != candidate.revision:
        raise ValidationError(
            "This event or document has a newer version. Review the latest candidate. / "
            "事件或正文已有新版本，请审核最新候选。"
        )
    document = (
        OfficialDocument.model_validate(candidate.revision.document)
        if candidate.revision.document
        else None
    )
    numbers = value.paragraphs
    if (
        not isinstance(numbers, list)
        or len(numbers) > 5
        or any(
            type(n) is not int or n < 1 or not document or n > len(document.text.split("\n\n"))
            for n in numbers
        )
        or len(set(numbers)) != len(numbers)
    ):
        raise ValidationError(
            "Select up to five distinct original paragraph numbers. / "
            "请选择最多五个不同的原文段落编号。"
        )
    if value.relation == "DIRECT" and not numbers:
        raise ValidationError(
            "Direct relevance requires an original paragraph citation. / 直接相关必须选择原文段落。"
        )
    if not value.rationale.strip():
        raise ValidationError("Explain the relationship to this event. / 请说明与本事件的关系。")
    if value.relation not in EventEvidenceReview.Relation.values:
        raise ValidationError("Invalid relevance classification.")


@transaction.atomic
def append_evidence_review(value: EventEvidenceReview) -> None:
    actor = value.reviewed_by
    if (
        not actor.is_active
        or not actor.is_staff
        or not actor.has_perm("research.add_eventevidencereview")
    ):
        raise PermissionDenied("Evidence review requires platform operator permission.")
    validate_review(value, lock=True)
    value.reviewed_at = timezone.now()
    value.full_clean()
    value.save()


def summary(value: EventDefinition, at: datetime) -> EventSummary:
    return EventSummary(
        id=value.event_id,
        slug=value.event.slug,
        definition_id=value.id,
        version=value.version,
        title=value.title,
        title_zh=value.title_zh,
        scope=value.scope,
        scope_zh=value.scope_zh,
        starts_on=value.starts_on,
        ends_on=value.ends_on,
        calendar_url=value.calendar_url,
        observed_at=value.observed_at,
        market_count=EventMarketLink.objects.filter(
            event_id=value.event_id, created_at__lte=at
        ).count(),
    )


def event_list(cutoff: datetime | None, market_id: UUID | None = None) -> list[EventSummary]:
    at = cutoff_time(cutoff)
    query = definitions(at)
    if market_id:
        query = query.filter(
            event__market_links__market_id=market_id, event__market_links__created_at__lte=at
        )
    return [summary(d, at) for d in query.order_by("starts_on", "event_id")[:20]]


def candidate_values(
    definition: EventDefinition, at: datetime
) -> tuple[list[EventEvidenceOut], bool]:
    latest = (
        EventEvidence.objects.filter(
            definition=definition,
            revision__item_id=OuterRef("revision__item_id"),
            created_at__lte=at,
            revision__observed_at__lte=at,
        )
        .order_by("-revision__version")
        .values("id")[:1]
    )
    candidates = list(
        EventEvidence.objects.filter(definition=definition, id=Subquery(latest))
        .select_related("revision__item__source")
        .defer("revision__raw_document")
        .order_by("-revision__observed_at", "id")[:101]
    )
    current_ids = set(
        visible_evidence(at)
        .filter(item_id__in=[c.revision.item_id for c in candidates])
        .values_list("id", flat=True)
    )
    result = []
    for candidate in candidates[:100]:
        revision = candidate.revision
        if revision.published_at and revision.published_at > at:
            continue
        reviews = list(
            candidate.reviews.filter(reviewed_at__lte=at).order_by("-reviewed_at", "-id")[:20]
        )
        review = reviews[0] if reviews else None
        status = (
            "STALE" if revision.id not in current_ids else review.relation if review else "PENDING"
        )
        document = OfficialDocument.model_validate(revision.document) if revision.document else None
        paragraphs = document.text.split("\n\n") if document else []
        # Public passages are bounded; the exact complete version is always accessible.
        passages = (
            [
                Passage(
                    paragraph=n,
                    text=paragraphs[n - 1][:2000],
                    truncated=len(paragraphs[n - 1]) > 2000,
                )
                for n in review.paragraphs
                if 0 < n <= len(paragraphs)
            ]
            if review
            else []
        )
        result.append(
            EventEvidenceOut(
                id=candidate.id,
                evidence=evidence_value(revision),
                status=cast(
                    Literal["PENDING", "STALE", "DIRECT", "BACKGROUND", "UNRELATED"], status
                ),
                review=EventReviewOut.from_orm(review) if review else None,
                passages=passages,
                history=[EventReviewOut.from_orm(r) for r in reviews],
                matched_at=candidate.created_at,
            )
        )
    order = {"DIRECT": 0, "BACKGROUND": 1, "PENDING": 2, "STALE": 3, "UNRELATED": 4}
    result.sort(
        key=lambda c: (
            order[c.status],
            -(c.evidence.published_at or c.evidence.observed_at).timestamp(),
            str(c.id),
        )
    )
    return result, len(candidates) > 100


def event_detail(slug: str, cutoff: datetime | None) -> EventDetail:
    at = cutoff_time(cutoff)
    definition = get_object_or_404(definitions(at), event__slug=slug)
    evidence, truncated = candidate_values(definition, at)
    markets = []
    for link in EventMarketLink.objects.filter(event=definition.event, created_at__lte=at).order_by(
        "created_at", "id"
    )[:100]:
        value = link.snapshot
        markets.append(
            EventContract(
                id=link.market_id,
                platform=value["platform"],
                title=value["market"]["title"],
                outcome=value["outcome"]["label"],
                resolution_rules=value["market"]["resolution_rules"],
                closes_at=value["market"].get("closes_at"),
                linked_at=link.created_at,
            )
        )
    changes: list[EventChange] = []
    for d in EventDefinition.objects.filter(event=definition.event, observed_at__lte=at).order_by(
        "-version"
    )[:20]:
        changes.append(
            EventChange(id=str(d.id), kind="SCOPE", title=d.title, observed_at=d.observed_at)
        )
    for c in (
        EventEvidence.objects.filter(
            definition__event=definition.event, created_at__lte=at, revision__observed_at__lte=at
        )
        .select_related("revision")
        .annotate(
            had_earlier_version=Exists(
                EventEvidence.objects.filter(
                    definition__event_id=OuterRef("definition__event_id"),
                    revision__item_id=OuterRef("revision__item_id"),
                    revision__version__lt=OuterRef("revision__version"),
                    created_at__lt=OuterRef("created_at"),
                )
            )
        )
        .defer("revision__document", "revision__raw_document")
        .order_by("-created_at")[:50]
    ):
        if c.revision.published_at and c.revision.published_at > at:
            continue
        changes.append(
            EventChange(
                id=str(c.id),
                kind="REVISION" if c.had_earlier_version else "EVIDENCE",
                title=c.revision.title,
                observed_at=c.created_at,
                item_id=c.revision.item_id,
                evidence_observed_at=c.revision.observed_at,
            )
        )
    for r in (
        EventEvidenceReview.objects.filter(
            candidate__definition__event=definition.event, reviewed_at__lte=at
        )
        .select_related("candidate__revision")
        .defer("candidate__revision__document", "candidate__revision__raw_document")
        .order_by("-reviewed_at")[:50]
    ):
        changes.append(
            EventChange(
                id=str(r.id),
                kind="REVIEW",
                title=r.candidate.revision.title,
                observed_at=r.reviewed_at,
                item_id=r.candidate.revision.item_id,
                evidence_observed_at=r.candidate.revision.observed_at,
            )
        )
    for m in markets:
        changes.append(
            EventChange(id=str(m.id), kind="MARKET", title=m.title, observed_at=m.linked_at)
        )
    changes.sort(key=lambda x: (x.observed_at, x.id), reverse=True)
    return EventDetail(
        event=summary(definition, at),
        cutoff=at,
        markets=markets,
        evidence=evidence,
        changes=changes[:50],
        counts={
            s: sum(e.status == s for e in evidence)
            for s in ("PENDING", "STALE", "DIRECT", "BACKGROUND", "UNRELATED")
        },
        truncated=truncated,
    )


def market_event_evidence(market_id: UUID, cutoff: datetime) -> list[dict[str, Any]]:
    """Only current, version-bound human reviews can enrich Agent evidence."""
    result = []
    for event in event_list(cutoff, market_id)[:5]:
        definition = EventDefinition.objects.get(pk=event.definition_id)
        candidates, _ = candidate_values(definition, cutoff)
        for candidate in candidates:
            if candidate.status != "STALE":
                result.append(
                    {
                        "event": event.model_dump(mode="json"),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
    result.sort(
        key=lambda item: (
            item["candidate"]["status"] != "DIRECT",
            item["candidate"]["evidence"]["observed_at"],
        )
    )
    return result
