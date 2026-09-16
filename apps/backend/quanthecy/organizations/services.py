from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils.text import slugify

from quanthecy.accounts.models import User

from .models import Organization, OrganizationMembership
from .policies import require_org_member, require_org_role

Role = OrganizationMembership.Role


@transaction.atomic
def create_organization(
    *,
    owner: User,
    name: str,
    kind: str = Organization.Kind.TEAM,
) -> Organization:
    owner = User.objects.select_for_update(no_key=True).get(pk=owner.pk)
    if not owner.is_active:
        raise PermissionDenied("An active owner is required")
    name = name.strip()
    if not name or len(name) > 120 or kind not in Organization.Kind.values:
        raise ValidationError("Invalid organization name or kind")
    organization = Organization.objects.create(
        name=name,
        kind=kind,
        slug=f"{slugify(name)[:100] or 'workspace'}-{uuid4().hex}",
    )
    OrganizationMembership.objects.create(organization=organization, user=owner, role=Role.OWNER)
    return organization


def list_memberships(
    user: User, *, limit: int = 50, offset: int = 0
) -> list[OrganizationMembership]:
    return list(
        OrganizationMembership.objects.filter(user=user)
        .select_related("organization")
        .order_by("created_at", "id")[offset : offset + limit]
    )


def list_members(
    *, actor: User, organization_id: UUID, limit: int = 50, offset: int = 0
) -> list[OrganizationMembership]:
    require_org_member(actor, organization_id)
    return list(
        OrganizationMembership.objects.filter(organization_id=organization_id)
        .select_related("user")
        .order_by("created_at", "id")[offset : offset + limit]
    )


def _lock_organization(organization_id: UUID) -> None:
    # All membership writes lock the parent first, serializing last-owner decisions.
    if not Organization.objects.select_for_update().filter(id=organization_id).exists():
        raise Http404("Organization not found")


@transaction.atomic
def rename_organization(*, actor: User, organization_id: UUID, name: str) -> Organization:
    _lock_organization(organization_id)
    membership = require_org_role(actor, organization_id, {Role.OWNER, Role.ADMIN})
    name = name.strip()
    if not name or len(name) > 120:
        raise ValidationError("Organization name must contain 1–120 characters")
    organization = membership.organization
    organization.name = name
    organization.save(update_fields=["name", "updated_at"])
    return organization


def _target(organization_id: UUID, membership_id: UUID) -> OrganizationMembership:
    try:
        return OrganizationMembership.objects.get(id=membership_id, organization_id=organization_id)
    except OrganizationMembership.DoesNotExist as exc:
        raise Http404("Membership not found") from exc


def _protect_last_owner(target: OrganizationMembership) -> None:
    if (
        target.role == Role.OWNER
        and not OrganizationMembership.objects.filter(
            organization_id=target.organization_id,
            role=Role.OWNER,
            user__is_active=True,
        )
        .exclude(id=target.id)
        .exists()
    ):
        raise ValidationError("Transfer ownership before removing or demoting the last owner")


@transaction.atomic
def change_member_role(
    *,
    actor: User,
    organization_id: UUID,
    membership_id: UUID,
    role: str,
) -> OrganizationMembership:
    _lock_organization(organization_id)
    acting = require_org_role(actor, organization_id, {Role.OWNER, Role.ADMIN})
    target = _target(organization_id, membership_id)
    if role not in Role.values:
        raise ValidationError("Invalid organization role")
    if acting.role == Role.ADMIN and (
        target.role in {Role.OWNER, Role.ADMIN} or role in {Role.OWNER, Role.ADMIN}
    ):
        raise PermissionDenied("Only owners manage owner and admin roles")
    if target.role == Role.OWNER and role != Role.OWNER:
        _protect_last_owner(target)
    if role == Role.OWNER and not target.user.is_active:
        raise ValidationError("An owner must have an active account")
    target.role = role
    target.save(update_fields=["role", "updated_at"])
    return target


@transaction.atomic
def remove_member(*, actor: User, organization_id: UUID, membership_id: UUID) -> None:
    _lock_organization(organization_id)
    acting = require_org_member(actor, organization_id)
    target = _target(organization_id, membership_id)
    if target.user_id != actor.id:
        if acting.role not in {Role.OWNER, Role.ADMIN}:
            raise PermissionDenied("Only owners and admins can remove other members")
        if acting.role == Role.ADMIN and target.role in {Role.OWNER, Role.ADMIN}:
            raise PermissionDenied("Only owners can remove owners and admins")
    _protect_last_owner(target)
    target.delete()
