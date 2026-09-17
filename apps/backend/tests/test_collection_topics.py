import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import CollectionPlan, CollectionTarget, Market, ResearchTopic
from quanthecy.markets.selection import (
    ACK_KEY,
    PLAN_ID,
    lock_plan,
    manifest,
    market_id,
    publish_selection,
    selection_status,
    validate_exchange_id,
)
from quanthecy.markets.topics import coverage
from quanthecy.operations.models import PlatformAuditLog
from quanthecy_analytics.signals import analyze

pytestmark = pytest.mark.django_db


@pytest.fixture
def topic():
    return ResearchTopic.objects.create(slug="fed-test", name="Fed test", name_zh="议息测试")


def target(topic, exchange_id="123", **fields):
    return CollectionTarget.objects.create(
        topic=topic,
        platform="polymarket",
        exchange_id=exchange_id,
        label="Example",
        rationale="Test scope",
        **fields,
    )


@pytest.fixture
def market():
    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )
    for row in rows:
        row["market"]["exchange_id"] = "12345"
        row["market"]["id"] = str(market_id("polymarket", "12345"))
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    return Market.objects.get()


def test_manifest_deduplicates_memberships_and_pauses_without_erasing_history(topic, market):
    target(topic, market.exchange_id)
    second = ResearchTopic.objects.create(slug="second", name="Second")
    target(second, market.exchange_id)
    plan = CollectionPlan.objects.create(managed=True)
    assert manifest(plan)["universe"]["polymarket"] == [market.exchange_id]
    topic.enabled = False
    topic.save()
    assert len(manifest(plan)["universe"]["polymarket"]) == 1
    second.enabled = False
    second.save()
    assert manifest(plan)["universe"] == {"polymarket": [], "kalshi": []}
    assert Market.objects.filter(pk=market.pk).exists()


@pytest.mark.parametrize(
    "platform,exchange_id",
    [
        ("polymarket", "1/2"),
        ("kalshi", "../X"),
        ("kalshi", "abc"),
        ("other", "123"),
        ("polymarket", "１２３"),
    ],
)
def test_invalid_exchange_identifiers_rejected(platform, exchange_id):
    with pytest.raises(ValidationError):
        validate_exchange_id(platform, exchange_id)


def test_limits_consider_deduplication_and_topic_activation(topic):
    for index in range(50):
        target(topic, str(index))
    duplicate = CollectionTarget(
        topic=ResearchTopic.objects.create(slug="copy", name="Copy"),
        platform="polymarket",
        exchange_id="0",
        label="Copy",
        rationale="Copy",
    )
    duplicate.full_clean()
    duplicate.save()
    with pytest.raises(ValidationError, match="50"):
        CollectionTarget(
            topic=topic, platform="polymarket", exchange_id="51", label="Excess", rationale="Test"
        ).full_clean()
    paused = ResearchTopic.objects.create(slug="paused", name="Paused", enabled=False)
    target(paused, "51")
    paused.enabled = True
    with pytest.raises(ValidationError, match="50"):
        paused.full_clean()


def test_operator_form_audits_atomic_changes_and_viewer_cannot_edit(topic):
    actor = User.objects.create_superuser("ops@example.com", "test-only")
    client = Client()
    client.force_login(actor)
    row = target(topic)
    CollectionPlan.objects.create(managed=True)
    data = {
        "topic": str(topic.id),
        "platform": row.platform,
        "exchange_id": row.exchange_id,
        "label": row.label,
        "rationale": row.rationale,
        "tier": row.tier,
        "change_reason": "Pause this market",
    }
    url = reverse("admin:markets_collectiontarget_change", args=[row.id])
    assert client.post(url, data).status_code == 302
    row.refresh_from_db()
    assert not row.enabled
    plan = CollectionPlan.objects.get(pk=PLAN_ID)
    assert plan.revision == 2
    audit = PlatformAuditLog.objects.get()
    assert audit.subject_id == row.id and audit.actor_id == actor.id
    assert audit.details["before"]["enabled"] and not audit.details["after"]["enabled"]
    assert (
        client.post(
            reverse("admin:markets_collectiontarget_delete", args=[row.id]), {"post": "yes"}
        ).status_code
        == 403
    )
    viewer = User.objects.create_user("viewer@example.com", is_staff=True)
    viewer.user_permissions.add(
        Permission.objects.get(content_type__app_label="markets", codename="view_collectiontarget")
    )
    client.force_login(viewer)
    assert client.get(url).status_code == 200
    assert client.post(url, {**data, "enabled": "on"}).status_code == 403
    assert CollectionPlan.objects.get().revision == 2


def test_invalid_operator_edit_leaves_plan_and_audit_unchanged(topic):
    client = Client()
    client.force_login(User.objects.create_superuser("edit@example.com", "test-only"))
    row = target(topic)
    CollectionPlan.objects.create(managed=True)
    response = client.post(
        reverse("admin:markets_collectiontarget_change", args=[row.id]),
        {
            "topic": str(topic.id),
            "platform": "polymarket",
            "exchange_id": "../bad",
            "label": "Bad",
            "rationale": "Test",
            "enabled": "on",
            "change_reason": "Invalid edit",
        },
    )
    assert response.status_code == 200 and response.context_data["adminform"].form.errors
    row.refresh_from_db()
    assert row.exchange_id == "123"
    assert CollectionPlan.objects.get().revision == 1
    assert not PlatformAuditLog.objects.exists()


def test_publisher_does_not_activate_uninitialized_plans_and_emits_bounded_snapshot(topic):
    with patch("quanthecy.markets.selection.Redis.from_url") as cache:
        publish_selection()
        cache.assert_not_called()
        with transaction.atomic():
            plan = lock_plan()
            plan.managed = True
            plan.save()
        target(topic)
        publish_selection()
        args, kwargs = cache.return_value.__enter__.return_value.set.call_args
        assert json.loads(args[1])["universe"]["polymarket"] == ["123"]
        assert kwargs["ex"] == 300


def test_ack_requires_fresh_matching_applied_revision():
    CollectionPlan.objects.create(managed=True, revision=4)
    with patch("quanthecy.markets.selection.Redis.from_url") as cache:
        redis = cache.return_value.__enter__.return_value
        for revision, age, enabled, expected in [
            (4, 0, True, True),
            (3, 0, True, False),
            (4, 181, True, False),
            (4, 0, False, False),
        ]:
            redis.get.return_value = json.dumps(
                {
                    "revision": revision,
                    "enabled": enabled,
                    "checked_at": (timezone.now() - timedelta(seconds=age)).isoformat(),
                }
            )
            assert selection_status()["applied"] is expected
            redis.get.assert_called_with(ACK_KEY)
        redis.get.return_value = b"invalid"
        assert not selection_status()["applied"]


def test_public_topic_filter_counts_missing_and_hides_operator_only_topics(topic, market):
    target(topic, market.exchange_id)
    target(topic, "999999")
    private = ResearchTopic.objects.create(slug="internal", name="Internal", is_public=False)
    target(private, "777")
    client = Client()
    assert client.get("/api/v1/research/topics").status_code == 401
    client.force_login(User.objects.create_user("reader@example.com"))
    reports = client.get("/api/v1/research/topics").json()
    assert len(reports) == 1
    assert reports[0]["configured"] == 2 and reports[0]["missing"] == 1
    assert reports[0]["price_usable"] == 0  # Historic fixture is currently stale.
    assert client.get("/api/v1/markets?topic=fed-test").json()["total"] == 1
    assert client.get("/api/v1/markets?topic=internal").status_code == 404
    topic.enabled = False
    topic.save()
    assert client.get("/api/v1/markets?topic=fed-test").status_code == 404
    assert coverage([topic])[1][topic.slug][0].state == "paused"


def test_coverage_console_permissions_language_and_missing_target(topic):
    target(topic)
    client = Client()
    actor = User.objects.create_user("coverage@example.com", is_staff=True)
    client.force_login(actor)
    url = reverse("platform_ops:collection_coverage")
    assert client.get(url).status_code == 403
    actor.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="operations", codename="view_collection_status"
        )
    )
    with patch("quanthecy.markets.selection.Redis.from_url", side_effect=OSError):
        response = client.get(url)
        assert response.status_code == 200 and "等待首次采集" in response.content.decode()
        client.cookies["quanthecy_admin_language"] = "en"
        assert b"Awaiting first observation" in client.get(url).content
        assert client.get(url + "?topic=unknown").status_code == 400


def test_bootstrap_preserves_existing_markets_is_idempotent_and_rolls_back_invalid_import(
    tmp_path, market
):
    actor = User.objects.create_superuser("bootstrap@example.com", "test-only")
    path = tmp_path / "topic.json"
    value = {
        "slug": "fed-import",
        "name": "Fed import",
        "targets": [
            {
                "platform": "kalshi",
                "exchange_id": "KXFED-TEST",
                "label": "Test",
                "rationale": "Test import",
            },
        ],
    }
    path.write_text(json.dumps(value))
    call_command("import_collection_topic", str(path), actor=actor.email)
    plan = CollectionPlan.objects.get()
    assert plan.managed
    assert manifest(plan)["universe"] == {
        "polymarket": [market.exchange_id],
        "kalshi": ["KXFED-TEST"],
    }
    revision = plan.revision
    call_command("import_collection_topic", str(path), actor=actor.email)
    assert CollectionPlan.objects.get().revision == revision
    value["slug"] = "bad-import"
    value["targets"][0]["exchange_id"] = "../BAD"
    path.write_text(json.dumps(value))
    with pytest.raises(Exception, match="market ID|合约代码"):
        call_command("import_collection_topic", str(path), actor=actor.email)
    assert not ResearchTopic.objects.filter(slug="bad-import").exists()
    assert CollectionPlan.objects.get().revision == revision
