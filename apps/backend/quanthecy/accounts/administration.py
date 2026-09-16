from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from quanthecy.agents.models import AgentRun
from quanthecy.operations.models import PlatformAuditLog
from quanthecy.operations.policies import require_operator
from quanthecy.organizations.models import Organization, OrganizationMembership

from .models import User


@transaction.atomic
def set_account_active(*, actor: User, user_id: UUID, active: bool, reason: str) -> User:
    require_operator(actor, "accounts.change_user")
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValidationError("Provide an operation reason of 1–500 characters.")
    # No key is changed: permit concurrent FK references while serializing status changes.
    user = User.objects.select_for_update(no_key=True).get(pk=user_id)
    if user.pk == actor.pk:
        raise ValidationError("You cannot change your own account status here.")
    if (user.is_staff or user.is_superuser) and not actor.is_superuser:
        raise PermissionDenied("Only a superuser can manage another platform operator.")
    if user.is_active == active:
        return user
    if not active:
        organization_ids = OrganizationMembership.objects.filter(user=user).values(
            "organization_id"
        )
        organizations = list(
            Organization.objects.select_for_update().filter(pk__in=organization_ids).order_by("pk")
        )
        for organization in organizations:
            owners = OrganizationMembership.objects.filter(
                organization=organization, role="OWNER", user__is_active=True
            )
            if owners.filter(user=user).exists() and not owners.exclude(user=user).exists():
                raise ValidationError(
                    "Transfer ownership before disabling the last active owner of "
                    f"{organization.name}."
                )
        AgentRun.objects.filter(requested_by=user, state__in=["PENDING", "RUNNING"]).update(
            state="CANCELLED",
            stage="cancelled",
            error_code="account_disabled",
            finished_at=timezone.now(),
        )
    user.is_active = active
    user.save(update_fields=["is_active"])
    PlatformAuditLog.objects.create(
        actor=actor,
        action="user.activated" if active else "user.deactivated",
        subject_id=user.pk,
        reason=reason,
        details={"is_active": active},
    )
    return user
