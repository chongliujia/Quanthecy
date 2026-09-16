from unittest.mock import patch
from uuid import UUID

import pytest
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from quanthecy.accounts.admin import AccountCreationForm
from quanthecy.accounts.models import AuthIdentity, User
from quanthecy.accounts.services import register_user
from quanthecy.organizations.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


def test_user_identity_and_password():
    user = User.objects.create_user("  Alice@EXAMPLE.com  ", "test-password-123")
    assert isinstance(user.id, UUID)
    assert user.email == "alice@example.com"
    assert user.password != "test-password-123"
    assert user.check_password("test-password-123")
    assert user.email_verified_at is None
    assert not user.is_staff and not user.is_superuser
    assert authenticate(email="ALICE@example.com", password="test-password-123") == user
    assert not hasattr(user, "username")


@pytest.mark.parametrize("email", ["", "   ", "invalid", "no-at.example.com"])
def test_invalid_email_rejected(email):
    with pytest.raises((ValueError, ValidationError)):
        User.objects.create_user(email, "password")


def test_case_insensitive_uniqueness_is_enforced_by_postgres():
    User.objects.create_user("alice@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email="ALICE@example.com")])


def test_superuser_flags_and_password():
    user = User.objects.create_superuser("Admin@example.com", "admin-password-123")
    assert user.is_staff and user.is_superuser and user.is_active
    assert user.check_password("admin-password-123")


@pytest.mark.parametrize(
    "flags", [{"is_staff": False}, {"is_superuser": False}, {"is_active": False}]
)
def test_superuser_rejects_invalid_flags(flags):
    with pytest.raises(ValueError):
        User.objects.create_superuser("admin@example.com", "password", **flags)


def test_superuser_requires_password():
    with pytest.raises(ValueError):
        User.objects.create_superuser("admin@example.com")


def test_admin_creation_form_normalizes_email_and_hashes_password():
    form = AccountCreationForm(
        data={
            "email": "Operator@EXAMPLE.com",
            "password1": "Operator-pass-147!",
            "password2": "Operator-pass-147!",
            "usable_password": "true",
        }
    )
    assert form.is_valid(), form.errors
    user = form.save()
    assert user.email == "operator@example.com"
    assert user.check_password("Operator-pass-147!")


def test_registration_creates_personal_workspace_transactionally():
    user = register_user(email="alice@example.com", password="Unusual-research-pass-920!")
    membership = OrganizationMembership.objects.get(user=user)
    assert membership.role == OrganizationMembership.Role.OWNER
    assert membership.organization.kind == Organization.Kind.PERSONAL
    assert not user.is_staff


def test_registration_rolls_back_if_owner_creation_fails():
    with (
        patch(
            "quanthecy.organizations.services.OrganizationMembership.objects.create",
            side_effect=RuntimeError("simulated write failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        register_user(email="alice@example.com", password="Unusual-research-pass-920!")
    assert not User.objects.exists()
    assert not Organization.objects.exists()


def test_registration_validates_password():
    with pytest.raises(ValidationError):
        register_user(email="alice@example.com", password="123")
    assert not User.objects.exists()


def test_external_identity_unique_by_provider_and_subject_without_email_linking():
    alice = User.objects.create_user("alice@example.com")
    bob = User.objects.create_user("bob@example.com")
    AuthIdentity.objects.create(
        user=alice, provider="github", subject="123", email="same@example.com"
    )
    AuthIdentity.objects.create(
        user=bob, provider="google", subject="123", email="same@example.com"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AuthIdentity.objects.create(user=bob, provider="github", subject="123")
    assert User.objects.count() == 2


def test_deleting_owner_cannot_cascade_organization():
    user = register_user(email="alice@example.com", password="Unusual-research-pass-920!")
    with pytest.raises(ProtectedError):
        user.delete()
    assert Organization.objects.count() == 1
