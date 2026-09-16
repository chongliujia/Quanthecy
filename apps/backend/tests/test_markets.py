import copy
import json
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.db import transaction
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.markets.ingestion import process_batch, reconcile
from quanthecy.markets.models import IngestionCheckpoint, Market, Outcome
from quanthecy_analytics.signals import analyze
from quanthecy_analytics.storage.clickhouse import AnalyticsUnavailable, ClickHouseRepository

pytestmark = pytest.mark.django_db


@pytest.fixture
def observations():
    return json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )


@pytest.fixture
def market(observations):
    with transaction.atomic():
        reconcile(observations[-1], analyze(observations)[0])
    return Market.objects.get()


@pytest.fixture
def client():
    client = Client()
    client.force_login(User.objects.create_user("researcher@example.com", "secret-password"))
    return client


def test_public_market_data_still_requires_authenticated_session(market):
    client = Client()
    for path in (
        "markets",
        f"markets/{market.id}",
        f"markets/{market.id}/history",
        f"markets/{market.id}/export",
        f"markets/{market.id}/signals",
    ):
        assert client.get(f"/api/v1/{path}").status_code == 401


def test_market_listing_filters_and_stale_rank_exclusion(client, market):
    page = client.get("/api/v1/markets").json()
    assert page["total"] == 1
    assert page["items"][0]["stale"]
    assert client.get("/api/v1/markets?sort=movement").json()["total"] == 0
    assert client.get("/api/v1/markets?platform=kalshi").json()["total"] == 0
    assert client.get("/api/v1/markets?search=missing").json()["total"] == 0
    Market.objects.filter(id=market.id).update(last_observed_at=timezone.now())
    assert client.get("/api/v1/markets?sort=movement").json()["total"] == 1
    assert client.get("/api/v1/markets?limit=-1").status_code == 422


def test_out_of_order_metadata_cannot_overwrite_newer_observation(market, observations):
    old = copy.deepcopy(observations[0])
    old["market"]["title"] = "Old title"
    with transaction.atomic():
        reconcile(old, analyze([old])[0])
    market.refresh_from_db()
    assert market.latest["observation_id"] == observations[-1]["observation_id"]
    assert market.title != "Old title"
    assert market.first_observed_at.isoformat().startswith("2026-01-01T12:00:00")
    assert Outcome.objects.count() == 1


def test_history_window_validation_bounded_results_and_unavailable_service(
    client, market, observations
):
    repository = Mock(spec=ClickHouseRepository)
    repository.history.return_value = observations
    with patch("quanthecy.markets.services.history_repository", return_value=repository):
        response = client.get(f"/api/v1/markets/{market.id}/history?limit=2")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2
        assert response.json()["truncated"]
        assert (
            client.get(f"/api/v1/markets/{market.id}/history?start=2026-01-01").status_code == 422
        )
        assert (
            client.get(
                f"/api/v1/markets/{market.id}/history?start=2026-01-01T00:00:00Z&end=2026-02-01T00:00:00Z"
            ).status_code
            == 422
        )
        repository.history.side_effect = AnalyticsUnavailable("History unavailable")
        assert client.get(f"/api/v1/markets/{market.id}/history").status_code == 503
    assert client.get(f"/api/v1/markets/{uuid4()}/history").status_code == 404


def test_detail_falls_back_to_persisted_state_after_redis_loss(client, market):
    with patch("quanthecy.markets.services.Redis.from_url", side_effect=OSError("offline")):
        response = client.get(f"/api/v1/markets/{market.id}")
    assert response.status_code == 200
    assert not response.json()["live_cache"]
    assert response.json()["latest"]["observation_id"] == market.latest["observation_id"]


def test_checkpoint_is_atomic_and_incomplete_batch_is_never_acknowledged(observations):
    collector = uuid4()
    repository = Mock(spec=ClickHouseRepository)
    repository.next_batch.return_value = {"batch_id": 1, "row_count": 16}
    repository.batch.return_value = observations[:-1]
    with pytest.raises(ValueError, match="Incomplete"):
        process_batch(repository, collector)
    assert IngestionCheckpoint.objects.get().batch_id == 0
    assert Market.objects.count() == 0
    repository.batch.return_value = observations
    repository.history.side_effect = lambda market, **kw: [
        o for o in observations if o["received_at"] <= kw["end"].replace("+00:00", "Z")
    ]
    repository.save_signals.side_effect = RuntimeError("storage failed")
    with pytest.raises(RuntimeError):
        process_batch(repository, collector)
    assert IngestionCheckpoint.objects.get().batch_id == 0
    assert Market.objects.count() == 0


def test_signal_export_refuses_incomplete_evidence(client, observations):
    repository = Mock(spec=ClickHouseRepository)
    signal = analyze(observations)[1][0]
    repository.signal.return_value = signal
    repository.signal_inputs.return_value = observations[:-1]
    with patch("quanthecy.markets.services.history_repository", return_value=repository):
        assert client.get(f"/api/v1/signals/{signal['id']}/inputs").status_code == 422
        repository.signal_inputs.return_value = observations
        response = client.get(f"/api/v1/signals/{signal['id']}/inputs")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert b"envelope_json" in response.content


def test_collection_status_survives_cache_loss_and_requires_login(client, market):
    assert Client().get("/api/v1/collection/status").status_code == 401
    with patch("quanthecy.markets.collection.Redis.from_url", side_effect=ConnectionError):
        response = client.get("/api/v1/collection/status")
    assert response.status_code == 200
    sources = {source["platform"]: source for source in response.json()["sources"]}
    assert sources["polymarket"]["state"] == "delayed"
    assert sources["polymarket"]["delay_seconds"] > 180
    assert sources["polymarket"]["error_code"] is None
    assert sources["kalshi"]["state"] == "empty"
    assert sources["kalshi"]["delay_seconds"] is None


def test_collection_status_ignores_expired_or_unsafe_diagnostics(client, market):
    from datetime import timedelta

    Market.objects.filter(id=market.id).update(last_observed_at=timezone.now())
    cache = Mock()
    with patch("quanthecy.markets.collection.Redis.from_url") as factory:
        factory.return_value.__enter__.return_value = cache
        cache.mget.return_value = [
            json.dumps({"checked_at": timezone.now().isoformat(), "error_code": "network"}),
            json.dumps(
                {
                    "checked_at": (timezone.now() - timedelta(minutes=6)).isoformat(),
                    "error_code": "network",
                }
            ),
        ]
        sources = client.get("/api/v1/collection/status").json()["sources"]
        assert sources[0]["state"] == "recent"
        assert sources[0]["fresh_markets"] == 1
        assert sources[0]["error_code"] == "network"
        assert sources[1]["collector_checked_at"] is None
        cache.mget.return_value = [
            json.dumps(
                {
                    "checked_at": timezone.now().isoformat(),
                    "error_code": "https://secret:token@private-proxy.test",
                }
            ),
            b"{broken",
        ]
        response = client.get("/api/v1/collection/status")
        assert response.status_code == 200
        assert "secret" not in response.content.decode()
        assert all(source["error_code"] is None for source in response.json()["sources"])
