from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import close_old_connections
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from quanthecy.accounts.administration import set_account_active
from quanthecy.accounts.models import User
from quanthecy.agents.models import AgentRun
from quanthecy.markets.models import IngestionCheckpoint
from quanthecy.operations.models import PlatformAuditLog, RawPayloadDeletion
from quanthecy.operations.raw_data import (
    claim_deletion,
    enqueue_deletion,
    finish_deletion,
    preview_deletion,
    process_deletion,
)
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.services import create_organization
from quanthecy_analytics.storage.clickhouse import AnalyticsUnavailable
from quanthecy_analytics.storage.raw import RawScope, RawWindow

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator():
    return User.objects.create_superuser("operator@example.com", "test-password")


@pytest.fixture
def window():
    end = timezone.now()
    return RawWindow(platform="polymarket", start=end - timedelta(hours=1), end=end)


def staff_with(*permissions):
    user = User.objects.create_user(f"{uuid4()}@example.com", is_staff=True)
    for key in permissions:
        app, name = key.split(".")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app, codename=name)
        )
    return user


def queued_job(operator, window):
    scope = RawScope(window=window, checkpoints={uuid4(): 4})
    return RawPayloadDeletion.objects.create(
        requested_by=operator,
        reason="Retention request",
        scope=scope.model_dump(mode="json"),
        preview_count=2,
    )


def expire(job):
    RawPayloadDeletion.objects.filter(pk=job.pk).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )


def test_disabling_preserves_history_and_revokes_login_and_pending_agent(operator):
    user = User.objects.create_user("researcher@example.com", "test-password")
    organization = create_organization(owner=operator, name="Research")
    membership = OrganizationMembership.objects.create(
        organization=organization, user=user, role="MEMBER"
    )
    run = AgentRun.objects.create(
        organization=organization,
        requested_by=user,
        idempotency_key=uuid4(),
        cutoff=timezone.now(),
        configuration_revision=1,
    )
    client = Client()
    client.force_login(user)
    set_account_active(actor=operator, user_id=user.pk, active=False, reason="Support request")
    assert authenticate(email=user.email, password="test-password") is None
    assert client.get("/api/v1/me").status_code == 401
    run.refresh_from_db()
    assert run.state == "CANCELLED" and run.error_code == "account_disabled"
    assert OrganizationMembership.objects.filter(pk=membership.pk).exists()
    assert PlatformAuditLog.objects.get().subject_id == user.pk
    set_account_active(actor=operator, user_id=user.pk, active=True, reason="Restored")
    assert authenticate(email=user.email, password="test-password") is not None


def test_status_protects_self_privileges_and_last_active_owner(operator):
    owner = User.objects.create_user("owner@example.com")
    organization = create_organization(owner=owner, name="Owned")
    inactive = User.objects.create_user("inactive@example.com", is_active=False)
    OrganizationMembership.objects.create(organization=organization, user=inactive, role="OWNER")
    with pytest.raises(ValidationError, match="Transfer ownership"):
        set_account_active(actor=operator, user_id=owner.pk, active=False, reason="test")
    with pytest.raises(ValidationError, match="own account"):
        set_account_active(actor=operator, user_id=operator.pk, active=False, reason="test")
    support = staff_with("accounts.change_user")
    with pytest.raises(PermissionDenied):
        set_account_active(actor=support, user_id=operator.pk, active=False, reason="test")
    assert not PlatformAuditLog.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_disables_cannot_remove_both_active_owners():
    operator = User.objects.create_superuser("operator@example.com", "password")
    owners = [User.objects.create_user(f"owner{i}@example.com") for i in range(2)]
    organization = create_organization(owner=owners[0], name="Research")
    OrganizationMembership.objects.create(organization=organization, user=owners[1], role="OWNER")
    barrier = Barrier(2)

    def disable(user_id):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            set_account_active(
                actor=User.objects.get(pk=operator.pk), user_id=user_id, active=False, reason="test"
            )
            return True
        except ValidationError:
            return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(disable, [owner.pk for owner in owners]))
    assert sorted(outcomes) == [False, True]
    assert organization.memberships.filter(role="OWNER", user__is_active=True).count() == 1


def test_stale_user_cannot_create_organization_after_disabling(operator):
    user = User.objects.create_user("user@example.com")
    set_account_active(actor=operator, user_id=user.pk, active=False, reason="test")
    with pytest.raises(PermissionDenied):
        create_organization(owner=user, name="Race")


def test_support_cannot_grant_privileges_or_edit_operator_password(operator):
    support = staff_with("accounts.view_user", "accounts.change_user")
    client = Client()
    client.force_login(support)
    user = User.objects.create_user("user@example.com")
    group = Group.objects.create(name="Elevated")
    response = client.post(
        reverse("admin:accounts_user_change", args=[user.pk]),
        {
            "is_active": "",
            "is_staff": "on",
            "is_superuser": "on",
            "groups": [group.pk],
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert (
        user.is_active and not user.is_staff and not user.is_superuser and not user.groups.exists()
    )
    assert (
        client.get(reverse("admin:auth_user_password_change", args=[operator.pk])).status_code
        == 403
    )
    request = RequestFactory().get("/admin/")
    request.user = operator
    assert "is_superuser" in admin.site._registry[User].get_readonly_fields(request, operator)


def test_admin_uses_platform_permissions_and_csrf(window):
    user = User.objects.create_user("customer@example.com")
    create_organization(owner=user, name="Customer")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.get(reverse("platform_ops:raw_payloads")).status_code == 302
    staff = staff_with()
    client.force_login(staff)
    assert client.get(reverse("platform_ops:raw_payloads")).status_code == 403
    viewer = staff_with("operations.view_raw_payloads")
    client.force_login(viewer)
    assert (
        client.post(
            reverse("platform_ops:raw_payloads"), window.model_dump(mode="json", exclude_none=True)
        ).status_code
        == 403
    )
    unchecked = Client()
    unchecked.force_login(viewer)
    assert (
        unchecked.post(
            reverse("platform_ops:raw_payloads"), window.model_dump(mode="json", exclude_none=True)
        ).status_code
        == 403
    )
    assert unchecked.get(reverse("platform_ops:confirm_deletion")).status_code == 405
    assert not RawPayloadDeletion.objects.exists()


def test_raw_detail_escapes_exchange_html(operator):
    client = Client()
    client.force_login(operator)
    with patch("quanthecy.operations.admin_views.repository") as repo:
        repo.return_value.observation.return_value = {
            "raw_payload": '<script>alert("x")</script>',
            "envelope": "{}",
        }
        response = client.get(reverse("platform_ops:raw_observation", args=[uuid4(), uuid4()]))
    assert response.status_code == 200
    assert b"&lt;script&gt;" in response.content and b'<script>alert("x")' not in response.content


def test_operator_preview_confirmation_and_readonly_job_pages(operator, window):
    client = Client(enforce_csrf_checks=True)
    client.force_login(operator)
    with patch("quanthecy.operations.admin_views.repository") as repo:
        repo.return_value.observations.return_value = []
        response = client.get(reverse("platform_ops:raw_payloads"))
    assert response.status_code == 200
    csrf = client.cookies["csrftoken"].value
    with patch("quanthecy.operations.raw_data.repository") as repo:
        repo.return_value.summary.return_value = {
            "eligible": 2,
            "protected": 1,
            "observations": 3,
            "cleared": 0,
        }
        response = client.post(
            reverse("platform_ops:raw_payloads"),
            {
                **window.model_dump(mode="json", exclude_none=True),
                "csrfmiddlewaretoken": csrf,
            },
        )
    assert response.status_code == 200
    token = response.context_data["confirmation"].initial["token"]
    assert not RawPayloadDeletion.objects.exists()
    response = client.post(
        reverse("platform_ops:confirm_deletion"),
        {
            "token": token,
            "reason": "Retention",
            "confirm": "on",
            "csrfmiddlewaretoken": csrf,
        },
    )
    assert response.status_code == 302
    job = RawPayloadDeletion.objects.get()
    assert (
        client.get(reverse("admin:operations_rawpayloaddeletion_change", args=[job.pk])).status_code
        == 200
    )
    assert (
        client.post(
            reverse("admin:operations_rawpayloaddeletion_change", args=[job.pk]),
            {
                "state": "SUCCEEDED",
                "csrfmiddlewaretoken": csrf,
            },
        ).status_code
        == 403
    )


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(days=-1), timedelta(days=8)])
def test_raw_time_window_must_be_increasing_and_bounded(delta):
    start = timezone.now()
    with pytest.raises(ValueError):
        RawWindow(platform="polymarket", start=start, end=start + delta)


def test_preview_freezes_watermarks_and_enqueue_is_actor_bound_and_idempotent(operator, window):
    collector = uuid4()
    IngestionCheckpoint.objects.create(collector_id=collector, batch_id=7)
    with patch("quanthecy.operations.raw_data.repository") as repo:
        repo.return_value.summary.return_value = {
            "eligible": 3,
            "protected": 2,
            "observations": 5,
            "cleared": 0,
        }
        summary, token = preview_deletion(operator, window)
        assert repo.return_value.summary.call_args.args[0].checkpoints == {collector: 7}
    IngestionCheckpoint.objects.filter(pk=collector).update(batch_id=9)
    other = staff_with("operations.purge_raw_payloads")
    with pytest.raises(ValidationError):
        enqueue_deletion(other, token, "test")
    with pytest.raises(ValidationError):
        enqueue_deletion(operator, token + "tampered", "test")
    with (
        patch("quanthecy.operations.raw_data.signing.loads", side_effect=signing.SignatureExpired),
        pytest.raises(ValidationError),
    ):
        enqueue_deletion(operator, token, "test")
    job = enqueue_deletion(operator, token, "Retention")
    assert enqueue_deletion(operator, token, "Repeat").pk == job.pk
    assert job.scope["checkpoints"] == {str(collector): 7}
    assert summary["eligible"] == job.preview_count == 3
    assert PlatformAuditLog.objects.count() == 1


@pytest.mark.parametrize("count", [0, 10001])
def test_unbounded_or_empty_cleanup_is_rejected(operator, window, count):
    with patch("quanthecy.operations.raw_data.repository") as repo:
        repo.return_value.summary.return_value = {"eligible": count}
        with pytest.raises(ValidationError):
            preview_deletion(operator, window)


def test_uncertain_submission_is_discovered_without_resubmitting(operator, window):
    job = queued_job(operator, window)
    storage = MagicMock()
    storage.summary.return_value = {"eligible": 2}
    storage.mutation_status.return_value = []
    storage.submit_deletion.side_effect = AnalyticsUnavailable()
    assert process_deletion(storage)
    job.refresh_from_db()
    assert job.state == "RUNNING" and job.error_code == "storage_unavailable"
    expire(job)
    storage.mutation_status.return_value = [{"is_done": 0, "has_failure": 0}]
    storage.summary.return_value = {"eligible": 0}
    assert process_deletion(storage)
    job.refresh_from_db()
    assert job.state == "RUNNING"  # No premature success while parts are still being mutated.
    expire(job)
    storage.mutation_status.return_value = [{"is_done": 1, "has_failure": 0}]
    assert process_deletion(storage)
    assert storage.submit_deletion.call_count == 1
    job.refresh_from_db()
    assert job.state == "SUCCEEDED"
    assert PlatformAuditLog.objects.filter(action="raw_payload.deletion_completed").count() == 1


def test_expired_worker_cannot_finish_reclaimed_job(operator, window):
    job = queued_job(operator, window)
    old_claim = claim_deletion()
    assert claim_deletion() is None
    expire(job)
    finish_deletion(old_claim)
    new_claim = claim_deletion()
    assert new_claim.lease_token != old_claim.lease_token
    finish_deletion(old_claim)
    job.refresh_from_db()
    assert job.state == "RUNNING" and not PlatformAuditLog.objects.exists()
    finish_deletion(new_claim)
    assert PlatformAuditLog.objects.count() == 1


def test_revoked_permission_blocks_unsubmitted_cleanup(operator, window):
    job = queued_job(operator, window)
    User.objects.filter(pk=operator.pk).update(is_active=False)
    storage = MagicMock()
    storage.summary.return_value = {"eligible": 2}
    storage.mutation_status.return_value = []
    process_deletion(storage)
    storage.submit_deletion.assert_not_called()
    job.refresh_from_db()
    assert job.state == "FAILED" and job.error_code == "authorization_revoked"


def test_standard_groups_do_not_grant_privilege_management():
    call_command("setup_operator_roles")
    call_command("setup_operator_roles")
    assert Group.objects.count() == 3
    viewer = Group.objects.get(name="Quanthecy data viewer")
    assert not viewer.permissions.filter(codename="purge_raw_payloads").exists()
    assert not Permission.objects.filter(
        group__in=Group.objects.all(), codename__in=["change_group", "delete_user"]
    ).exists()


def test_audit_only_operator_can_open_operations_app_index():
    viewer = staff_with("operations.view_platformauditlog")
    client = Client()
    client.force_login(viewer)
    response = client.get(reverse("admin:app_list", kwargs={"app_label": "operations"}))
    assert response.status_code == 200
    assert client.get(reverse("platform_ops:dashboard")).status_code == 403


def test_truncated_collection_list_does_not_claim_omitted_history_is_missing(operator):
    IngestionCheckpoint.objects.create(collector_id=uuid4(), batch_id=5)
    client = Client()
    client.force_login(operator)
    with (
        patch("quanthecy.operations.admin_views.repository") as repo,
        patch(
            "quanthecy.operations.admin_views.dependency_status", return_value={"postgres": True}
        ),
        patch("quanthecy.operations.admin_views.collection_status", return_value={"sources": []}),
    ):
        repo.return_value.collector_batches.return_value = [
            {"collector_id": str(uuid4()), "latest_batch": 7} for _ in range(101)
        ]
        response = client.get(reverse("platform_ops:dashboard"))
    assert response.status_code == 200
    assert len(response.context_data["batches"]) == 101
    assert all(row["latest_batch"] == 7 for row in response.context_data["batches"])
