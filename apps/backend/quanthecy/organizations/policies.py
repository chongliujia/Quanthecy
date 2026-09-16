from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.http import Http404

from quanthecy.accounts.models import User

from .models import OrganizationMembership


def require_org_member(user: User, organization_id: UUID) -> OrganizationMembership:
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied("An active account is required")
    try:
        return OrganizationMembership.objects.select_related("organization").get(
            user=user,
            organization_id=organization_id,
        )
    except OrganizationMembership.DoesNotExist as exc:
        raise Http404("Organization not found") from exc


def require_org_role(
    user: User,
    organization_id: UUID,
    roles: set[str],
) -> OrganizationMembership:
    membership = require_org_member(user, organization_id)
    if membership.role not in roles:
        raise PermissionDenied("Your organization role does not permit this action")
    return membership
