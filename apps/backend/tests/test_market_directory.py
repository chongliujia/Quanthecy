import json
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pydantic import ValidationError as SchemaError
from quanthecy.accounts.models import User
from quanthecy.markets.catalog import (
    configure_coverage,
    directory,
    discovery_health,
    reconcile_page,
    select_catalog,
)
from quanthecy.markets.models import (
    CatalogCheckpoint,
    CatalogMarket,
    CollectionPlan,
    CollectionTarget,
    Market,
    ResearchTopic,
)
from quanthecy.markets.selection import manifest, market_id
from quanthecy.operations.models import PlatformAuditLog

pytestmark = pytest.mark.django_db


def page(page_id=1, ids=("123",), observed=None):
    return {
        "schema_version": 1,
        "page_id": page_id,
        "platform": "polymarket",
        "observed_at": (observed or timezone.now()).isoformat(),
        "scan_id": str(uuid4()),
        "pages": 1,
        "rows_seen": len(ids),
        "accepted": len(ids),
        "skipped": 0,
        "state": "complete",
        "items": [
            {
                "id": str(market_id("polymarket", i)),
                "exchange_id": i,
                "title": f"Example {i}",
                "status": "OPEN",
                "closes_at": None,
                "volume_24h": 100.0,
                "volume_unit": "USD",
            }
            for i in ids
        ],
    }


@pytest.fixture
def operator():
    return User.objects.create_superuser("directory@example.com", "test")


@pytest.fixture
def topic():
    return ResearchTopic.objects.create(slug="directory", name="Directory research")


def test_pages_idempotent_ordered_and_metadata_cannot_invent_history():
    collector = uuid4()
    value = page()
    assert reconcile_page(collector, value)
    assert not reconcile_page(collector, value)
    assert CatalogMarket.objects.count() == 1 and not Market.objects.exists()
    with pytest.raises(ValueError, match="Missing"):
        reconcile_page(collector, page(3))
    assert CatalogCheckpoint.objects.get().page_id == 1
    stale = page(2, observed=timezone.now() - timedelta(days=1))
    stale["items"][0]["title"] = "Old title"
    reconcile_page(collector, stale)
    assert CatalogMarket.objects.get().title == "Example 123"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["items"][0].update(id=str(uuid4())),
        lambda p: p["items"][0].update(volume_24h=-1),
        lambda p: p["items"][0].update(volume_unit="CONTRACTS"),
        lambda p: p.update(observed_at="2026-09-17T12:00:00"),
        lambda p: p.update(accepted=5),
    ],
)
def test_invalid_page_does_not_advance_or_partially_write(mutate):
    value = page()
    mutate(value)
    with pytest.raises((ValueError, SchemaError)):
        reconcile_page(uuid4(), value)
    assert not CatalogMarket.objects.exists() and not CatalogCheckpoint.objects.exists()


def controls(**changes):
    return dict(
        revision=1,
        catalog_enabled=True,
        catalog_interval_seconds=3600,
        catalog_page_interval_seconds=10,
        catalog_max_pages=200,
        standard_interval_seconds=300,
        reason="Enable directory",
        **changes,
    )


def test_discovery_controls_versioned_audited_and_source_pause_remains(operator):
    CollectionPlan.objects.create(managed=True, polymarket_enabled=False)
    plan = configure_coverage(operator, controls())
    value = manifest(plan)
    assert value["schema_version"] == 3 and not value["sources"]["polymarket"]["enabled"]
    assert value["discovery"]["max_pages"] == 200 and plan.revision == 2
    assert PlatformAuditLog.objects.get().details["kind"] == "directory_controls"
    with pytest.raises(ValidationError):
        configure_coverage(operator, controls())
    with pytest.raises(PermissionDenied):
        configure_coverage(User.objects.create_user("customer@example.com", "test"), controls())


def test_discovery_health_requires_current_heartbeat_and_preserves_paused_state(monkeypatch):
    plan = CollectionPlan.objects.create(catalog_enabled=True, kalshi_enabled=False)
    cache = MagicMock()
    cache.__enter__.return_value = cache
    monkeypatch.setattr("redis.Redis.from_url", lambda *args, **kwargs: cache)
    now = timezone.now()
    for record, expected in [
        ({"checked_at": now.isoformat(), "revision": plan.revision}, "online"),
        ({"checked_at": now.isoformat(), "revision": 0}, "pending"),
        ({"checked_at": now.isoformat(), "revision": plan.revision, "error": True}, "error"),
        ({"checked_at": (now - timedelta(minutes=4)).isoformat()}, "offline"),
        ([], "offline"),
    ]:
        cache.mget.return_value = [json.dumps(record), None]
        assert discovery_health() == [
            {"platform": "polymarket", "state": expected},
            {"platform": "kalshi", "state": "paused"},
        ]


def test_bulk_selection_tier_deduplication_and_capacity_rollback(operator, topic):
    plan = CollectionPlan.objects.create(managed=True)
    ids = [str(n) for n in range(51)]
    reconcile_page(uuid4(), page(ids=ids))

    def select(selected, tier="priority", revision=1):
        return select_catalog(
            operator,
            ids=[market_id("polymarket", i) for i in selected],
            topic_id=topic.pk,
            tier=tier,
            revision=revision,
            reason="Scope expansion",
        )

    assert select(ids[:50]) == 50
    with pytest.raises(ValidationError):
        select([ids[-1]], revision=2)
    assert CollectionTarget.objects.count() == 50 and PlatformAuditLog.objects.count() == 1
    assert select([ids[-1]], tier="standard", revision=2) == 1
    plan.refresh_from_db()
    value = manifest(plan)
    assert len(value["universe"]["polymarket"]) == 51
    assert value["intervals"]["polymarket"][ids[-1]] == 300
    assert value["intervals"]["polymarket"][ids[0]] == 60
    other = ResearchTopic.objects.create(slug="other", name="Other")
    CollectionTarget.objects.create(
        topic=other,
        platform="polymarket",
        exchange_id=ids[0],
        label="Example",
        rationale="Test",
        tier="standard",
    )
    assert manifest(plan)["intervals"]["polymarket"][ids[0]] == 60


def test_stale_closed_invalid_and_replayed_bulk_forms_are_rejected(operator, topic):
    CollectionPlan.objects.create(managed=True)
    reconcile_page(uuid4(), page())
    values = dict(
        ids=[market_id("polymarket", "123")],
        topic_id=topic.pk,
        tier="standard",
        revision=1,
        reason="Test",
    )
    CatalogMarket.objects.update(last_seen_at=timezone.now() - timedelta(days=2))
    with pytest.raises(ValidationError):
        select_catalog(operator, **values)
    CatalogMarket.objects.update(last_seen_at=timezone.now(), status="RESOLVED")
    with pytest.raises(ValidationError):
        select_catalog(operator, **values)
    assert not CollectionTarget.objects.exists()


def test_directory_api_auth_and_escaping_and_admin_permissions(operator):
    value = page(ids=("123", "124"))
    value["items"][0]["title"] = "<script>test</script>"
    reconcile_page(uuid4(), value)
    client = Client()
    assert client.get("/api/v1/market-directory").status_code == 401
    user = User.objects.create_user("reader@example.com", "test")
    client.force_login(user)
    result = client.get("/api/v1/market-directory?platform=polymarket&search=script").json()
    assert (
        result["total"] == 1
        and not result["items"][0]["has_history"]
        and result["items"][0]["collection"] == "directory"
    )
    assert client.get("/api/v1/market-directory?limit=1001").status_code == 422
    user.is_staff = True
    user.save()
    assert client.get(reverse("platform_ops:market_directory")).status_code == 403
    assert (
        client.post(
            reverse("platform_ops:market_directory"), {"action": "configure", **controls()}
        ).status_code
        == 403
    )
    client.force_login(operator)
    response = client.get(reverse("platform_ops:market_directory"))
    assert response.status_code == 200 and b"<script>test</script>" not in response.content
    assert "市场发现" in response.content.decode()
    client.cookies["quanthecy_admin_language"] = "en"
    assert (
        "Market discovery" in client.get(reverse("platform_ops:market_directory")).content.decode()
    )
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(operator)
    assert (
        csrf.post(
            reverse("platform_ops:market_directory"), {"action": "configure", **controls()}
        ).status_code
        == 403
    )


def test_ranking_keeps_source_units_and_pagination():
    value = page(ids=("123", "124"))
    value["items"][1]["volume_24h"] = 200
    reconcile_page(uuid4(), value)
    result = directory(platform="polymarket", limit=1)
    assert result.items[0].exchange_id == "124" and result.total == 2
    assert directory(platform="polymarket", offset=1, limit=1).items[0].exchange_id == "123"
