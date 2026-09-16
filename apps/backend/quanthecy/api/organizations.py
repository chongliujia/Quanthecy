from uuid import UUID

from django.http import HttpRequest
from ninja import Query, Router, Status

from quanthecy.organizations import services
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.policies import require_org_member

from .auth import current_user
from .schemas import MembershipOut, Message, OrganizationInput, OrganizationOut, RoleInput

router = Router(tags=["Organizations"])


@router.get("", response=list[OrganizationOut])
def organizations(
    request: HttpRequest,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[OrganizationOut]:
    return [
        OrganizationOut.from_organization(m.organization, m.role)
        for m in services.list_memberships(current_user(request), limit=limit, offset=offset)
    ]


@router.post("", response={201: OrganizationOut})
def create(request: HttpRequest, payload: OrganizationInput) -> Status[OrganizationOut]:
    org = services.create_organization(owner=current_user(request), name=payload.name)
    return Status(201, OrganizationOut.from_organization(org, OrganizationMembership.Role.OWNER))


@router.get("/{organization_id}", response=OrganizationOut)
def detail(request: HttpRequest, organization_id: UUID) -> OrganizationOut:
    membership = require_org_member(current_user(request), organization_id)
    return OrganizationOut.from_organization(membership.organization, membership.role)


@router.patch("/{organization_id}", response=OrganizationOut)
def rename(
    request: HttpRequest, organization_id: UUID, payload: OrganizationInput
) -> OrganizationOut:
    user = current_user(request)
    org = services.rename_organization(
        actor=user, organization_id=organization_id, name=payload.name
    )
    return OrganizationOut.from_organization(org, require_org_member(user, organization_id).role)


@router.get("/{organization_id}/members", response=list[MembershipOut])
def members(
    request: HttpRequest,
    organization_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[MembershipOut]:
    return [
        MembershipOut.from_membership(m)
        for m in services.list_members(
            actor=current_user(request),
            organization_id=organization_id,
            limit=limit,
            offset=offset,
        )
    ]


@router.patch("/{organization_id}/members/{membership_id}", response=MembershipOut)
def change_role(
    request: HttpRequest,
    organization_id: UUID,
    membership_id: UUID,
    payload: RoleInput,
) -> MembershipOut:
    return MembershipOut.from_membership(
        services.change_member_role(
            actor=current_user(request),
            organization_id=organization_id,
            membership_id=membership_id,
            role=payload.role,
        )
    )


@router.delete("/{organization_id}/members/{membership_id}", response=Message)
def remove(request: HttpRequest, organization_id: UUID, membership_id: UUID) -> Message:
    services.remove_member(
        actor=current_user(request), organization_id=organization_id, membership_id=membership_id
    )
    return Message(detail="Membership removed")
