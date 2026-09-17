"""Version-bound event research. Matching is discovery, operator review is evidence."""

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, QuerySet, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .discovery import discover
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
from .evidence_changes import revision_changes
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
            .order_by("-observed_at", "id")[:500]
        )
        matched = 0
        for revision in revisions:
            discovery = discover(definition, revision)
            if discovery is None:
                continue
            _, added = EventEvidence.objects.get_or_create(
                definition=definition,
                revision=revision,
                defaults={"discovery": discovery, "discovery_priority": discovery["priority"]},
            )
            created += int(added)
            matched += 1
            if matched >= 100:
                break
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
    quote = value.feed_quote.strip()
    if quote and (
        len(quote) < 12
        or not any(quote in text for text in (candidate.revision.title, candidate.revision.excerpt))
    ):
        raise ValidationError(
            "Quote 12–1000 exact characters from the saved title or excerpt. / "
            "请引用已保存标题或摘要中的 12–1000 个连续字符。"
        )
    value.feed_quote = quote
    if value.relation == "DIRECT" and not (numbers or quote):
        raise ValidationError(
            "Direct relevance requires an original paragraph or exact feed quote. / "
            "直接相关必须引用原文段落或订阅摘要。"
        )
    if not value.rationale.strip():
        raise ValidationError("Explain the relationship to this event. / 请说明与本事件的关系。")
    if value.relation not in EventEvidenceReview.Relation.values:
        raise ValidationError("Invalid relevance classification.")
    if value.stance not in EventEvidenceReview.Stance.values:
        raise ValidationError("Invalid outcome stance.")
    if value.stance != "UNKNOWN" and (value.relation != "DIRECT" or not value.target_contract_id):
        raise ValidationError(
            "Support/opposition requires direct relevance and an explicit contract outcome. / "
            "支持或反对必须直接相关并指定合约结果。"
        )
    if value.target_contract_id:
        target = EventMarketLink.objects.get(pk=value.target_contract_id)
        value.target_contract = target
        if target.event_id != candidate.definition.event_id:
            raise ValidationError("Choose a contract linked to this event. / 请选择本事件的合约。")
        from quanthecy.markets.models import Market

        market_query = Market.objects.select_for_update() if lock else Market.objects
        market = market_query.get(pk=target.market_id)
        if not contract_matches(target.snapshot, market.latest):
            raise ValidationError(
                "Contract rules or outcome changed since linking; "
                "the saved target cannot support a new stance. / "
                "合约规则或结果已变化，请先核查保存的合约范围。"
            )


def contract_matches(saved: dict[str, Any], current: dict[str, Any]) -> bool:
    return (
        bool(current)
        and saved.get("outcome") == current.get("outcome")
        and all(
            saved.get("market", {}).get(key) == current.get("market", {}).get(key)
            for key in ("id", "title", "resolution_rules", "rules_version", "closes_at")
        )
    )


def review_value(value: EventEvidenceReview) -> EventReviewOut:
    target = value.target_contract
    return EventReviewOut(
        id=value.id,
        relation=cast(Literal["DIRECT", "BACKGROUND", "UNRELATED"], value.relation),
        rationale=value.rationale,
        paragraphs=value.paragraphs,
        reviewed_at=value.reviewed_at,
        feed_quote=value.feed_quote,
        stance=cast(Literal["UNKNOWN", "SUPPORTS", "OPPOSES"], value.stance),
        target_contract_id=value.target_contract_id,
        target_market_id=target.market_id if target else None,
        target_snapshot=target.snapshot if target else None,
    )


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
        .prefetch_related(
            Prefetch(
                "reviews",
                queryset=EventEvidenceReview.objects.filter(reviewed_at__lte=at)
                .select_related("target_contract")
                .order_by("-reviewed_at", "-id")[:20],
                to_attr="cutoff_reviews",
            )
        )
        .defer("revision__raw_document", "revision__raw_feed_fields")
        .annotate(
            previous_revision_id=Subquery(
                EvidenceRevision.objects.filter(
                    item_id=OuterRef("revision__item_id"),
                    version__lt=OuterRef("revision__version"),
                    observed_at__lte=at,
                )
                .order_by("-version")
                .values("id")[:1]
            )
        )
        .order_by("-discovery_priority", "-revision__observed_at", "id")[:101]
    )
    previous_versions = EvidenceRevision.objects.defer("raw_document", "raw_feed_fields").in_bulk(
        [c.previous_revision_id for c in candidates if c.previous_revision_id]
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
        reviews = candidate.cutoff_reviews
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
                review=review_value(review) if review else None,
                passages=passages,
                history=[review_value(r) for r in reviews],
                matched_at=candidate.created_at,
                discovery=candidate.discovery,
                changes=revision_changes(
                    revision, previous_versions.get(candidate.previous_revision_id)
                ),
            )
        )
    order = {"DIRECT": 0, "BACKGROUND": 1, "PENDING": 2, "STALE": 3, "UNRELATED": 4}
    result.sort(
        key=lambda c: (
            order[c.status],
            -c.discovery.get("priority", 0),
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
        official_direct_count=sum(
            e.status == "DIRECT"
            and e.evidence.source_kind == "OFFICIAL"
            and bool(e.review and e.review.paragraphs)
            for e in evidence
        ),
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
