import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.markets.collection import collection_status
from quanthecy.markets.controls import configure_collection
from quanthecy.markets.models import CollectionPlan
from quanthecy.markets.selection import manifest, publish_selection, selection_status
from quanthecy.operations.models import PlatformAuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator():
    return User.objects.create_superuser("controls@example.com", "test-password")


def values(**changes):
    return {
        "revision": 1,
        "polymarket_enabled": False,
        "polymarket_interval_seconds": 60,
        "kalshi_enabled": True,
        "kalshi_interval_seconds": 120,
        "reason": "Operator test",
        **changes,
    }


def test_controls_preserve_scope_and_audit_before_after(operator):
    plan = configure_collection(operator, values())
    assert plan.controls_managed and not plan.managed
    assert not plan.polymarket_enabled and plan.kalshi_enabled and plan.revision == 2
    payload = manifest(plan)
    assert payload["schema_version"] == 2 and payload["enabled"] is False
    assert payload["sources"]["kalshi"]["interval_seconds"] == 120
    event = PlatformAuditLog.objects.get()
    assert event.actor == operator and event.details["before"]["sources"]["polymarket"]["enabled"]
    with patch("quanthecy.markets.selection.Redis.from_url") as cache:
        publish_selection()
        published = json.loads(cache.return_value.__enter__.return_value.set.call_args.args[1])
        assert published == payload
    # Editing target selection must not disable the runtime controls.
    plan.managed = True
    plan.save()
    configure_collection(operator, values(revision=2, polymarket_enabled=True))
    plan.refresh_from_db()
    assert plan.managed and plan.polymarket_enabled and plan.revision == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"polymarket_interval_seconds": 14},
        {"kalshi_interval_seconds": 3601},
        {"kalshi_interval_seconds": "1.5"},
        {"reason": " "},
    ],
)
def test_invalid_controls_leave_no_partial_plan_or_audit(operator, changes):
    with pytest.raises(ValidationError):
        configure_collection(operator, values(**changes))
    assert not CollectionPlan.objects.exists() and not PlatformAuditLog.objects.exists()


def test_stale_form_cannot_overwrite_newer_controls(operator):
    configure_collection(operator, values())
    with pytest.raises(ValidationError):
        configure_collection(operator, values(polymarket_enabled=True))
    assert not CollectionPlan.objects.get().polymarket_enabled
    assert PlatformAuditLog.objects.count() == 1


def test_database_enforces_poll_bounds():
    with pytest.raises(IntegrityError), transaction.atomic():
        CollectionPlan.objects.create(kalshi_interval_seconds=0)


def test_staff_permission_and_csrf_are_required(operator):
    url = reverse("platform_ops:collection_controls")
    staff = User.objects.create_user("staff@example.com", "test", is_staff=True)
    client = Client()
    client.force_login(staff)
    assert client.get(url).status_code == 403
    assert client.post(url, values()).status_code == 403
    with pytest.raises(PermissionDenied):
        configure_collection(staff, values())
    staff.user_permissions.add(Permission.objects.get(codename="change_collectionplan"))
    staff = User.objects.get(pk=staff.pk)
    assert client.get(url).status_code == 200
    configure_collection(staff, values())
    staff.is_staff = False
    staff.save()
    with pytest.raises(PermissionDenied):
        configure_collection(staff, values(revision=2))
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(operator)
    assert csrf.post(url, values(revision=2)).status_code == 403


def test_bilingual_form_save_invalid_interval_and_conflict(operator):
    client = Client()
    client.force_login(operator)
    url = reverse("platform_ops:collection_controls")
    assert "采集控制" in client.get(url).content.decode()
    client.cookies["quanthecy_admin_language"] = "en"
    assert "Collection controls" in client.get(url).content.decode()
    assert client.post(url, values(kalshi_interval_seconds=5)).status_code == 200
    assert not PlatformAuditLog.objects.exists()
    assert client.post(url, values()).status_code == 302
    response = client.post(url, values())
    assert response.status_code == 200 and response.context_data["form"].non_field_errors()
    assert PlatformAuditLog.objects.count() == 1


def test_runtime_ack_requires_supported_version_and_recent_heartbeat(operator):
    plan = configure_collection(operator, values())
    ack = {"revision": plan.revision, "enabled": False, "checked_at": timezone.now().isoformat()}
    with patch("quanthecy.markets.selection.Redis.from_url") as cache:
        redis = cache.return_value.__enter__.return_value
        redis.get.return_value = json.dumps(ack)
        assert not selection_status()["applied"]  # Old collector cannot confirm runtime settings.
        ack["schema_version"] = 2
        redis.get.return_value = json.dumps(ack)
        assert selection_status()["applied"]
        ack["checked_at"] = (timezone.now() - timedelta(seconds=181)).isoformat()
        redis.get.return_value = json.dumps(ack)
        assert not selection_status()["applied"]


def test_pause_and_long_interval_use_control_heartbeat(operator):
    configure_collection(operator, values(kalshi_interval_seconds=3600))
    with patch("quanthecy.markets.selection.Redis.from_url") as cache:
        redis = cache.return_value.__enter__.return_value
        ack = json.dumps(
            {
                "revision": 2,
                "enabled": False,
                "schema_version": 2,
                "checked_at": timezone.now().isoformat(),
            }
        )
        redis.mget.return_value = [None, None]
        redis.get.side_effect = lambda key: ack if key == "collector:selection-status:v1" else None
        states = {s.platform: s.run_state for s in collection_status().sources}
        assert states == {"polymarket": "paused", "kalshi": "delayed"}
