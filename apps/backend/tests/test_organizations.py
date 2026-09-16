from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.http import Http404
from quanthecy.accounts.models import User
from quanthecy.organizations.models import Organization, OrganizationMembership
from quanthecy.organizations.policies import require_org_member
from quanthecy.organizations.services import (
    change_member_role,
    create_organization,
    remove_member,
    rename_organization,
)

pytestmark = pytest.mark.django_db
Role = OrganizationMembership.Role


@pytest.fixture
def owner():
    return User.objects.create_user("owner@example.com", "test-password")


@pytest.fixture
def organization(owner):
    return create_organization(owner=owner, name="Research team")


def test_user_can_belong_to_multiple_organizations(owner, organization):
    second = create_organization(owner=owner, name="Second team")
    assert second.id != organization.id
    assert OrganizationMembership.objects.filter(user=owner).count() == 2


def test_membership_uniqueness(owner, organization):
    with pytest.raises(IntegrityError), transaction.atomic():
        OrganizationMembership.objects.create(
            user=owner, organization=organization, role=Role.VIEWER
        )


def test_staff_has_no_implicit_membership(organization):
    staff = User.objects.create_superuser("staff@example.com", "staff-password")
    with pytest.raises(Http404):
        require_org_member(staff, organization.id)


def test_viewer_cannot_manage_organization(organization):
    viewer = User.objects.create_user("viewer@example.com")
    OrganizationMembership.objects.create(user=viewer, organization=organization, role=Role.VIEWER)
    with pytest.raises(PermissionDenied):
        rename_organization(actor=viewer, organization_id=organization.id, name="Changed")


def test_last_owner_cannot_leave_or_be_demoted(owner, organization):
    membership = OrganizationMembership.objects.get(user=owner, organization=organization)
    with pytest.raises(ValidationError):
        remove_member(actor=owner, organization_id=organization.id, membership_id=membership.id)
    with pytest.raises(ValidationError):
        change_member_role(
            actor=owner,
            organization_id=organization.id,
            membership_id=membership.id,
            role=Role.ADMIN,
        )


def test_ownership_can_be_transferred_then_previous_owner_can_leave(owner, organization):
    next_owner = User.objects.create_user("next@example.com")
    next_membership = OrganizationMembership.objects.create(
        user=next_owner, organization=organization, role=Role.MEMBER
    )
    old_membership = OrganizationMembership.objects.get(user=owner, organization=organization)
    change_member_role(
        actor=owner,
        organization_id=organization.id,
        membership_id=next_membership.id,
        role=Role.OWNER,
    )
    remove_member(actor=owner, organization_id=organization.id, membership_id=old_membership.id)
    assert OrganizationMembership.objects.get(organization=organization).user == next_owner


def test_membership_lookup_is_scoped_to_organization(owner, organization):
    another = create_organization(owner=owner, name="Other workspace")
    foreign_member = OrganizationMembership.objects.get(organization=another)
    with pytest.raises(Http404):
        change_member_role(
            actor=owner,
            organization_id=organization.id,
            membership_id=foreign_member.id,
            role=Role.VIEWER,
        )


def test_admin_cannot_promote_self_to_owner(owner, organization):
    admin = User.objects.create_user("admin@example.com")
    membership = OrganizationMembership.objects.create(
        user=admin, organization=organization, role=Role.ADMIN
    )
    with pytest.raises(PermissionDenied):
        change_member_role(
            actor=admin,
            organization_id=organization.id,
            membership_id=membership.id,
            role=Role.OWNER,
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_owners_cannot_both_leave():
    alice = User.objects.create_user("alice@example.com")
    bob = User.objects.create_user("bob@example.com")
    organization = create_organization(owner=alice, name="Concurrent owners")
    bob_membership = OrganizationMembership.objects.create(
        user=bob, organization=organization, role=Role.OWNER
    )
    alice_membership = OrganizationMembership.objects.get(user=alice, organization=organization)
    barrier = Barrier(2, timeout=10)

    def leave(user_id, membership_id):
        close_old_connections()
        try:
            actor = User.objects.get(id=user_id)
            barrier.wait()
            remove_member(actor=actor, organization_id=organization.id, membership_id=membership_id)
            return "removed"
        except ValidationError:
            return "protected"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(leave, alice.id, alice_membership.id),
            executor.submit(leave, bob.id, bob_membership.id),
        ]
        assert sorted(f.result(timeout=15) for f in futures) == ["protected", "removed"]
    assert (
        OrganizationMembership.objects.filter(organization=organization, role=Role.OWNER).count()
        == 1
    )
    assert Organization.objects.filter(id=organization.id).exists()
