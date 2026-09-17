"""Audited operator controls, independent of worker-owned health fields."""

from uuid import NAMESPACE_URL, uuid5

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from quanthecy.accounts.models import User
from quanthecy.operations.models import PlatformAuditLog

from .feed_registry import FEEDS
from .models import EvidenceItem, EvidenceSource


@transaction.atomic
def configure_source(
    slug: str, *, enabled: bool, interval: int, reason: str, actor: User
) -> EvidenceSource:
    if (
        not actor.is_active
        or not actor.is_staff
        or not actor.has_perm("research.change_evidencesource")
    ):
        raise PermissionDenied
    if slug not in FEEDS or not 300 <= interval <= 86400 or not reason.strip():
        raise ValidationError(
            "Choose a registered source, a 300–86400 second interval and a reason."
        )
    source = EvidenceSource.objects.select_for_update().get(pk=slug)
    before = {"enabled": source.enabled, "poll_interval_seconds": source.poll_interval_seconds}
    source.enabled = enabled
    source.poll_interval_seconds = interval
    # In-flight responses from the old configuration may not publish after an edit.
    source.poll_lease = None
    source.lease_expires_at = None
    source.next_poll_at = timezone.now()
    source.save(
        update_fields=[
            "enabled",
            "poll_interval_seconds",
            "poll_lease",
            "lease_expires_at",
            "next_poll_at",
        ]
    )
    EvidenceItem.objects.filter(source=source).update(document_lease=None)
    PlatformAuditLog.objects.create(
        actor=actor,
        action="news.source_configured",
        subject_id=uuid5(NAMESPACE_URL, f"quanthecy:evidence-source:{slug}"),
        reason=reason.strip()[:500],
        details={
            "source_slug": slug,
            "before": before,
            "after": {"enabled": enabled, "poll_interval_seconds": interval},
        },
    )
    return source
