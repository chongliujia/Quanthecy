import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from django.db import transaction
from django.test import Client
from quanthecy.accounts.models import User
from quanthecy.alerts.evaluation import evaluate_observation
from quanthecy.alerts.models import AlertCursor, AlertEvent, AlertRule
from quanthecy.alerts.schemas import RuleInput
from quanthecy.alerts.services import save_rule
from quanthecy.markets.ingestion import process_batch, reconcile
from quanthecy.markets.models import CollectionPlan, IngestionCheckpoint, Market
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.services import create_organization
from quanthecy.watchlists.models import WatchlistItem
from quanthecy.watchlists.services import add_item, save_list
from quanthecy_analytics.alert_metrics import evaluate_window
from quanthecy_analytics.signals import analyze
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository

pytestmark = pytest.mark.django_db
BASE = datetime(2026, 9, 17, 12, tzinfo=UTC)
TEMPLATE = json.loads(
    (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
)[0]


def window(end=BASE, minutes=15, move=0.05, spread=False):
    rows = []
    for index in range(minutes + 1):
        row = copy.deepcopy(TEMPLATE)
        at = (end - timedelta(minutes=minutes - index)).isoformat().replace("+00:00", "Z")
        row.update(observation_id=str(uuid4()), received_at=at, recorded_at=at)
        midpoint = 0.4 if spread else 0.4 + move * index / minutes
        half = 0.01 + move * index / minutes / 2 if spread else 0.01
        row.update(best_bid=round(midpoint - half, 6), best_ask=round(midpoint + half, 6))
        row["probability"].update(value=round(midpoint, 6), as_of=at)
        row["volume"]["as_of"] = at
        rows.append(row)
    return rows


def metric(rows, minutes=15, kind="PROBABILITY_MOVE", now=BASE, **kwargs):
    return evaluate_window(
        rows,
        window_minutes=minutes,
        kind=kind,
        observation_id=rows[-1]["observation_id"],
        now=now,
        **kwargs,
    )


@pytest.mark.parametrize("minutes", [5, 15, 60])
def test_window_units_and_frozen_quote_inputs(minutes):
    result = metric(window(minutes=minutes), minutes=minutes)
    assert result["eligible"] and result["value_pp"] == 5
    assert len(result["inputs"]) == minutes + 1
    assert "rules_version" in result["inputs"][0]
    assert "raw_payload" not in result["inputs"][0]
    assert metric(window(minutes=minutes, spread=True), minutes, "SPREAD_WIDENING")["value_pp"] == 5


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("stale", "stale_observation"),
        ("stale_price", "stale_price"),
        ("future", "stale_observation"),
        ("gap", "sampling_gap_or_invalid_quote"),
        ("rules", "incompatible_observations"),
        ("missing", "missing_midpoint"),
        ("crossed", "invalid_quote"),
        ("duplicate", "conflicting_duplicate"),
        ("recorded_future", "future_observation"),
        ("source", "price_source_changed"),
        ("closed", "market_not_open"),
    ],
)
def test_window_rejects_unusable_data(fault, reason):
    rows = window()
    now = BASE
    if fault == "stale":
        now += timedelta(minutes=4)
    if fault == "stale_price":
        now += timedelta(minutes=2)
        rows[-1]["probability"]["as_of"] = (
            (BASE - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        )
    if fault == "future":
        now -= timedelta(minutes=1)
    if fault == "gap":
        del rows[5:8]
    if fault == "rules":
        rows[0]["market"]["rules_version"] = "old"
    if fault == "missing":
        rows[0]["probability"] = None
    if fault == "crossed":
        rows[0]["best_bid"] = 0.8
    if fault == "duplicate":
        duplicate = copy.deepcopy(rows[0])
        duplicate["best_bid"] = 0.7
        rows.insert(1, duplicate)
    if fault == "recorded_future":
        rows[-1]["recorded_at"] = (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    if fault == "source":
        rows[0]["probability"]["source"] = "another"
    if fault == "closed":
        rows[-1]["market"]["status"] = "CLOSED"
    result = metric(rows, now=now)
    assert not result["eligible"] and result["reason"] == reason
    assert result["value_pp"] is None


def test_bounded_history_and_exact_decimal_threshold():
    assert metric(window(move=0.005))["value_pp"] == 0.5
    assert metric(window()[-5:])["reason"] == "insufficient_history"
    assert metric(window(), truncated=True)["reason"] == "history_truncated"


@pytest.fixture
def setup():
    actor = User.objects.create_user("watcher@example.com", "a-secret-password")
    org = create_organization(owner=actor, name="Research")
    rows = window()
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    market = Market.objects.get()
    list_id = save_list(actor, org.id, "Rates")
    add_item(actor, org.id, list_id, market.id)
    payload = RuleInput(name="Move", kind="PROBABILITY_MOVE", threshold_pp=3)
    rule_id = save_rule(actor, org.id, list_id, payload)
    AlertRule.objects.filter(id=rule_id).update(effective_at=BASE - timedelta(hours=2))
    WatchlistItem.objects.update(added_at=BASE - timedelta(hours=2))
    client = Client()
    client.force_login(actor)
    return actor, org, market, list_id, rule_id, client


def evaluate(rows):
    repository = Mock(spec=ClickHouseRepository)
    repository.history.return_value = rows
    with patch(
        "quanthecy.alerts.evaluation.timezone.now",
        return_value=datetime.fromisoformat(rows[-1]["received_at"]),
    ):
        return evaluate_observation(repository, rows[-1])


def test_trigger_latch_rearm_cooldown_and_restart(setup):
    rows = window()
    assert evaluate(rows) == 1
    assert evaluate(rows) == 0  # Same observation after a worker restart.
    assert evaluate(window(end=BASE + timedelta(minutes=1))) == 0
    assert AlertCursor.objects.get().status == "LATCHED"
    assert evaluate(window(end=BASE + timedelta(minutes=2), move=0.01)) == 0
    assert AlertCursor.objects.get().armed
    assert evaluate(window(end=BASE + timedelta(minutes=3))) == 0
    assert AlertCursor.objects.get().status == "COOLDOWN"
    assert evaluate(window(end=BASE + timedelta(minutes=31))) == 1
    assert AlertEvent.objects.count() == 2


def test_invalid_data_does_not_rearm_and_rule_pause(setup):
    assert evaluate(window()) == 1
    invalid = window(end=BASE + timedelta(minutes=1))
    invalid[-1]["probability"] = None
    assert evaluate(invalid) == 0
    assert not AlertCursor.objects.get().armed
    assert evaluate(window(end=BASE + timedelta(minutes=40))) == 0
    AlertRule.objects.update(enabled=False)
    assert evaluate(window(end=BASE + timedelta(minutes=41), move=0.01)) == 0
    assert AlertEvent.objects.count() == 1


def test_stale_catchup_cannot_notify(setup):
    repository = Mock(spec=ClickHouseRepository)
    repository.history.return_value = window()
    with patch("quanthecy.alerts.evaluation.timezone.now", return_value=BASE + timedelta(hours=1)):
        assert evaluate_observation(repository, repository.history.return_value[-1]) == 0
    assert AlertCursor.objects.get().reason == "stale_observation"


def test_direction_and_no_retroactive_new_rules(setup):
    AlertRule.objects.update(direction="DOWN", effective_at=BASE + timedelta(seconds=1))
    assert evaluate(window(move=-0.05)) == 0
    assert evaluate(window(end=BASE + timedelta(minutes=1))) == 0
    assert evaluate(window(end=BASE + timedelta(minutes=2), move=-0.05)) == 1


def test_ingestion_checkpoint_and_notification_rollback(setup):
    rows = window()
    repository = Mock(spec=ClickHouseRepository)
    collector = uuid4()
    IngestionCheckpoint.objects.create(collector_id=collector)
    repository.next_batch.return_value = {"batch_id": 1, "row_count": 1}
    repository.batch.return_value = [rows[-1]]
    repository.history.return_value = rows
    with (
        patch("quanthecy.alerts.evaluation.timezone.now", return_value=BASE),
        patch(
            "quanthecy.markets.ingestion.IngestionCheckpoint.save",
            side_effect=RuntimeError("crash"),
        ),
        pytest.raises(RuntimeError),
    ):
        process_batch(repository, collector)
    assert IngestionCheckpoint.objects.get().batch_id == 0
    assert not AlertEvent.objects.exists() and not AlertCursor.objects.exists()
    with patch("quanthecy.alerts.evaluation.timezone.now", return_value=BASE):
        assert process_batch(repository, collector)
    assert AlertEvent.objects.count() == 1


def test_watchlist_api_scope_viewer_and_csrf(setup):
    actor, org, market, list_id, rule_id, client = setup
    base = f"/api/v1/organizations/{org.id}"
    assert (
        client.post(
            f"{base}/watchlists", {"name": "rates"}, content_type="application/json"
        ).status_code
        == 422
    )
    viewer = User.objects.create_user("viewer@example.com", "secret-password")
    OrganizationMembership.objects.create(user=viewer, organization=org, role="VIEWER")
    client.force_login(viewer)
    assert client.get(f"{base}/watchlists/{list_id}").status_code == 200
    for path, method, data in [
        ("/watchlists", "post", {"name": "Denied"}),
        (f"/watchlists/{list_id}", "patch", {"name": "Denied"}),
        (f"/watchlists/{list_id}/items", "post", {"market_id": str(market.id)}),
        (f"/watchlists/{list_id}", "delete", {}),
        (
            f"/watchlists/{list_id}/rules",
            "post",
            {"name": "Denied", "kind": "PROBABILITY_MOVE", "threshold_pp": 1},
        ),
    ]:
        assert (
            getattr(client, method)(base + path, data, content_type="application/json").status_code
            == 403
        )
    outsider = User.objects.create_superuser("staff@example.com", "secret-password")
    client.force_login(outsider)
    assert client.get(f"{base}/watchlists/{list_id}").status_code == 404
    assert (
        client.get(f"/api/v1/markets?watchlist_id={list_id}&organization_id={org.id}").status_code
        == 404
    )
    guarded = Client(enforce_csrf_checks=True)
    guarded.force_login(actor)
    assert (
        guarded.post(
            f"{base}/watchlists", {"name": "CSRF"}, content_type="application/json"
        ).status_code
        == 403
    )
    assert Client().get(f"{base}/watchlists").status_code == 401


def test_cross_workspace_ids_and_frozen_alert_history(setup):
    actor, org, market, list_id, rule_id, client = setup
    second = create_organization(owner=actor, name="Other")
    base = f"/api/v1/organizations/{org.id}"
    other = f"/api/v1/organizations/{second.id}"
    assert client.get(f"{other}/watchlists/{list_id}").status_code == 404
    assert evaluate(window()) == 1
    event = AlertEvent.objects.get()
    assert client.get(f"{other}/alerts/{event.id}").status_code == 404
    assert (
        client.patch(
            f"{other}/alerts/{event.id}/read", {"read": True}, content_type="application/json"
        ).status_code
        == 404
    )
    assert client.get(f"{base}/alerts").json()["unread"] == 1
    client.patch(f"{base}/alerts/{event.id}/read", {"read": True}, content_type="application/json")
    assert client.get(f"{base}/alerts?unread_only=true").json()["total"] == 0
    viewer = User.objects.create_user("reader@example.com", "secret-password")
    OrganizationMembership.objects.create(user=viewer, organization=org, role="VIEWER")
    client.force_login(viewer)
    assert client.get(f"{base}/alerts").json()["unread"] == 1
    assert (
        client.patch(
            f"{base}/alerts/{event.id}/read", {"read": True}, content_type="application/json"
        ).status_code
        == 200
    )
    client.force_login(actor)
    assert client.delete(f"{base}/watchlists/{list_id}").status_code == 200
    assert not AlertRule.objects.get().enabled
    assert client.get(f"{base}/watchlists").json() == []
    detail = client.get(f"{base}/alerts/{event.id}").json()
    assert len(detail["snapshot"]["calculation"]["inputs"]) == 16
    assert detail["threshold_pp"] == 3


def test_item_idempotency_and_order_validation(setup):
    _, org, market, list_id, _, client = setup
    base = f"/api/v1/organizations/{org.id}/watchlists/{list_id}"
    for _ in range(2):
        assert (
            client.post(
                f"{base}/items", {"market_id": str(market.id)}, content_type="application/json"
            ).status_code
            == 200
        )
    assert WatchlistItem.objects.count() == 1
    assert (
        client.put(f"{base}/order", {"market_ids": []}, content_type="application/json").status_code
        == 422
    )
    assert (
        client.put(
            f"{base}/order", {"market_ids": [str(market.id)]}, content_type="application/json"
        ).status_code
        == 200
    )
    assert client.delete(f"{base}/items/{market.id}").status_code == 200
    assert evaluate(window()) == 0


def test_collection_pause_and_missing_heartbeat_are_distinct(setup):
    *_, client = setup
    plan = CollectionPlan.objects.create(id=UUID(int=1), managed=True, revision=7)
    with (
        patch("quanthecy.markets.collection.Redis.from_url") as factory,
        patch(
            "quanthecy.markets.collection.selection_status",
            return_value={
                "managed": True,
                "desired_revision": 7,
                "applied_revision": 7,
                "applied": True,
            },
        ),
    ):
        cache = factory.return_value.__enter__.return_value
        cache.mget.return_value = [None, None]
        cache.get.return_value = None
        status = client.get("/api/v1/collection/status").json()
        assert all(source["run_state"] == "paused" for source in status["sources"])
        assert status["analytics_state"] == "no_heartbeat"
    plan.managed = False
    plan.save()
    with patch("quanthecy.markets.collection.Redis.from_url") as factory:
        cache = factory.return_value.__enter__.return_value
        cache.mget.return_value = [None, None]
        cache.get.return_value = None
        assert (
            client.get("/api/v1/collection/status").json()["sources"][0]["run_state"]
            == "no_heartbeat"
        )
    with patch("quanthecy.markets.collection.Redis.from_url", side_effect=OSError):
        assert (
            client.get("/api/v1/collection/status").json()["sources"][0]["run_state"] == "unknown"
        )


@pytest.mark.parametrize(
    "field,value",
    [("threshold_pp", 0), ("threshold_pp", 101), ("window_minutes", 10), ("cooldown_minutes", 0)],
)
def test_invalid_rule_input_cannot_change_saved_rule(setup, field, value):
    _, org, _, list_id, rule_id, client = setup
    before = AlertRule.objects.get().revision
    response = client.put(
        f"/api/v1/organizations/{org.id}/watchlists/{list_id}/rules/{rule_id}",
        {"name": "Changed", "kind": "PROBABILITY_MOVE", "threshold_pp": 3, field: value},
        content_type="application/json",
    )
    assert response.status_code == 422
    assert AlertRule.objects.get().revision == before


def test_rule_edit_keeps_frozen_alert_and_resumes_with_new_revision(setup):
    actor, org, _, list_id, rule_id, client = setup
    assert evaluate(window()) == 1
    original = AlertEvent.objects.get()
    original_snapshot = copy.deepcopy(original.snapshot)
    with patch("quanthecy.alerts.services.timezone.now", return_value=BASE + timedelta(minutes=1)):
        save_rule(
            actor,
            org.id,
            list_id,
            RuleInput(name="Spread", kind="SPREAD_WIDENING", direction="DOWN", threshold_pp=4),
            rule_id,
        )
    rule = AlertRule.objects.get()
    assert rule.revision == 2 and rule.direction == "UP"
    assert evaluate(window(end=BASE + timedelta(minutes=2), spread=True)) == 0
    assert AlertCursor.objects.get().status == "COOLDOWN"
    assert evaluate(window(end=BASE + timedelta(minutes=31), spread=True)) == 1
    original.refresh_from_db()
    assert original.snapshot == original_snapshot
    latest = AlertEvent.objects.first()
    assert latest.revision == 2 and latest.snapshot["rule"]["name"] == "Spread"
    # A rule from one list cannot be edited through a different list, even by the same owner.
    other = save_list(actor, org.id, "Other")
    response = client.put(
        f"/api/v1/organizations/{org.id}/watchlists/{other}/rules/{rule_id}",
        {"name": "Wrong list", "kind": "PROBABILITY_MOVE", "threshold_pp": 3},
        content_type="application/json",
    )
    assert response.status_code == 404


def test_collection_reports_pending_failed_and_active_states(setup):
    from quanthecy.markets.collection import collection_status, publish_analytics_heartbeat

    at = BASE.isoformat()
    Market.objects.update(last_observed_at=BASE)
    with (
        patch("quanthecy.markets.collection.Redis.from_url") as factory,
        patch("quanthecy.markets.collection.timezone.now", return_value=BASE),
        patch("quanthecy.markets.collection.selection_status") as plan,
    ):
        cache = factory.return_value.__enter__.return_value
        cache.mget.return_value = [json.dumps({"checked_at": at}), None]
        cache.get.return_value = at
        plan.return_value = {
            "managed": False,
            "desired_revision": 0,
            "applied_revision": None,
            "applied": False,
        }
        status = collection_status()
        assert status.sources[0].run_state == "active" and status.analytics_state == "active"
        cache.mget.return_value = [
            json.dumps({"checked_at": at, "error_code": "rate_limited"}),
            None,
        ]
        assert collection_status().sources[0].run_state == "request_failed"
        plan.return_value["managed"] = True
        assert collection_status().sources[0].run_state == "pause_pending"
        publish_analytics_heartbeat()
        cache.set.assert_called_once_with("worker:market-analytics:heartbeat:v1", at, ex=90)
