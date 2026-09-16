from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pydantic import ValidationError as SchemaError
from quanthecy_analytics.storage.clickhouse import AnalyticsUnavailable
from quanthecy_analytics.storage.raw import RawDataRepository, RawScope, RawWindow

from quanthecy.accounts.models import User
from quanthecy.markets.models import IngestionCheckpoint
from quanthecy.markets.repositories import history_repository

from .models import PlatformAuditLog, RawPayloadDeletion
from .policies import require_operator

MAX_DELETE_ROWS = 10000
SALT = "quanthecy.raw-payload-deletion.v1"


def repository() -> RawDataRepository:
    return RawDataRepository(history_repository())


def preview_deletion(actor: User, window: RawWindow) -> tuple[dict[str, int], str]:
    require_operator(actor, "operations.purge_raw_payloads")
    checkpoints = dict(IngestionCheckpoint.objects.values_list("collector_id", "batch_id")[:101])
    if len(checkpoints) > 100:
        raise ValidationError("Raw cleanup currently supports at most 100 collector checkpoints.")
    scope = RawScope(
        window=window,
        checkpoints=checkpoints,
    )
    summary = repository().summary(scope)
    if not 0 < summary["eligible"] <= MAX_DELETE_ROWS:
        raise ValidationError(
            "Choose a range with 1–10,000 eligible raw payloads. The current collector batch "
            "and unreconciled batches are protected."
        )
    token = signing.dumps(
        {
            "operation": str(uuid4()),
            "actor": str(actor.pk),
            "scope": scope.model_dump(mode="json"),
            "count": summary["eligible"],
        },
        salt=SALT,
        compress=True,
    )
    return summary, token


@transaction.atomic
def enqueue_deletion(actor: User, token: str, reason: str) -> RawPayloadDeletion:
    require_operator(actor, "operations.purge_raw_payloads")
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValidationError("Provide a deletion reason of 1–500 characters.")
    try:
        payload = signing.loads(token, salt=SALT, max_age=900)
        if payload["actor"] != str(actor.pk):
            raise ValueError("Another operator's preview")
        scope = RawScope.model_validate(payload["scope"])
        operation_id = UUID(payload["operation"])
        count = int(payload["count"])
        if not 0 < count <= MAX_DELETE_ROWS:
            raise ValueError("Invalid preview count")
    except (signing.BadSignature, ValueError, KeyError, TypeError, SchemaError) as exc:
        raise ValidationError(
            "The preview is invalid or expired. Preview the deletion again."
        ) from exc
    job, created = RawPayloadDeletion.objects.get_or_create(
        pk=operation_id,
        defaults={
            "requested_by": actor,
            "reason": reason,
            "scope": scope.model_dump(mode="json"),
            "preview_count": count,
        },
    )
    if created:
        PlatformAuditLog.objects.create(
            actor=actor,
            action="raw_payload.deletion_requested",
            subject_id=job.pk,
            reason=reason,
            details={"scope": job.scope, "preview_count": count},
        )
    return job


@transaction.atomic
def claim_deletion() -> RawPayloadDeletion | None:
    now = timezone.now()
    job = (
        RawPayloadDeletion.objects.select_for_update(skip_locked=True)
        .filter(Q(state="PENDING") | Q(state="RUNNING", lease_expires_at__lte=now))
        .order_by("created_at", "id")
        .first()
    )
    if job:
        job.state = "RUNNING"
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(minutes=2)
        job.save(update_fields=["state", "lease_token", "lease_expires_at"])
    return job


def owned_job(job: RawPayloadDeletion) -> Any:
    return RawPayloadDeletion.objects.filter(
        pk=job.pk,
        state="RUNNING",
        lease_token=job.lease_token,
        lease_expires_at__gt=timezone.now(),
    )


@transaction.atomic
def finish_deletion(job: RawPayloadDeletion, *, error: str = "") -> None:
    state = "FAILED" if error else "SUCCEEDED"
    if owned_job(job).update(state=state, error_code=error, finished_at=timezone.now()):
        PlatformAuditLog.objects.create(
            actor=job.requested_by,
            action="raw_payload.deletion_failed" if error else "raw_payload.deletion_completed",
            subject_id=job.pk,
            reason=job.reason,
            details={"preview_count": job.preview_count, "error_code": error},
        )


def process_deletion(storage: RawDataRepository | None = None) -> bool:
    """Submit one bounded mutation, or poll a prior submission; no work in HTTP requests."""
    job = claim_deletion()
    if job is None:
        return False
    storage = storage or repository()
    try:
        scope = RawScope.model_validate(job.scope)
        mutations = storage.mutation_status(job.pk)
        remaining = storage.summary(scope)["eligible"]
        if remaining == 0 and all(m["is_done"] for m in mutations):
            finish_deletion(job)
            return True
        if mutations:
            # ClickHouse can recover temporarily failed mutations. Keep polling instead
            # of claiming success or repeatedly submitting the same expensive mutation.
            if all(m["is_done"] for m in mutations):
                finish_deletion(job, error="payloads_remain_after_mutation")
                return True
            error = "storage_mutation_retrying" if any(m["has_failure"] for m in mutations) else ""
        else:
            actor = job.requested_by
            if (
                not actor.is_active
                or not actor.is_staff
                or not actor.has_perm("operations.purge_raw_payloads")
            ):
                finish_deletion(job, error="authorization_revoked")
                return True
            if job.attempts >= 3:
                finish_deletion(job, error="submission_unconfirmed")
                return True
            if remaining > MAX_DELETE_ROWS:
                finish_deletion(job, error="scope_exceeds_limit")
                return True
            if not owned_job(job).update(attempts=job.attempts + 1):
                return True
            storage.submit_deletion(job.pk, scope)
            error = ""
        owned_job(job).update(
            error_code=error, lease_expires_at=timezone.now() + timedelta(seconds=15)
        )
    except AnalyticsUnavailable:
        # An uncertain HTTP reply may already have submitted the mutation; discover it
        # by the operation ID on the next cycle before deciding whether to retry.
        owned_job(job).update(
            error_code="storage_unavailable",
            lease_expires_at=timezone.now() + timedelta(seconds=30),
        )
    except (ValueError, SchemaError):
        finish_deletion(job, error="invalid_scope")
    return True
