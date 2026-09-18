"""Optional real-ClickHouse checks; create/drop only a unique test-owned database."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from quanthecy.markets.ingestion import process_batch
from quanthecy.markets.models import Market
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository
from quanthecy_analytics.storage.migrate import migrate

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not os.environ.get("QUANTHECY_TEST_CLICKHOUSE_URL"),
        reason="Opt-in ClickHouse integration test",
    ),
]


@pytest.fixture
def repository():
    database = "quanthecy_test_" + uuid4().hex
    admin = ClickHouseRepository(
        url=os.environ["QUANTHECY_TEST_CLICKHOUSE_URL"],
        database="default",
        user=os.environ.get("QUANTHECY_TEST_CLICKHOUSE_USER", "quanthecy"),
        password=os.environ.get("QUANTHECY_TEST_CLICKHOUSE_PASSWORD", "quanthecy-dev-only"),
    )
    admin.execute(f"CREATE DATABASE {database}")
    repo = ClickHouseRepository(
        url=admin.url, database=database, user=admin.user, password=admin.password
    )
    try:
        assert migrate(repo) == [
            "0001_market_history",
            "0002_market_catalog",
            "0003_execution_quotes",
        ]
        assert migrate(repo) == []
        yield repo
    finally:
        admin.execute(f"DROP DATABASE {database} SYNC")


def test_real_batch_replay_history_deduplication_and_signal_reproduction(repository):
    from quanthecy_analytics.signals import analyze

    observations = json.loads((Path(__file__).parent / "fixtures/research-window.json").read_text())
    collector = uuid4()
    records = [
        {
            "collector_id": str(collector),
            "batch_id": 1,
            "observation_id": o["observation_id"],
            "platform": o["platform"],
            "market_id": o["market"]["id"],
            "outcome_id": o["outcome"]["id"],
            "received_at": o["received_at"],
            "probability": o["probability"]["value"],
            "best_bid": o["best_bid"],
            "best_ask": o["best_ask"],
            "volume": o["volume"]["value"],
            "volume_unit": o["volume"]["unit"],
            "quality_flags": o["quality_flags"],
            "envelope": json.dumps(o),
            "raw_payload": "{}",
        }
        for o in observations
    ]
    insert = (
        "INSERT INTO market_observations SETTINGS date_time_input_format='best_effort' "
        "FORMAT JSONEachRow\n"
    )
    for _ in range(2):
        repository.execute(insert + "\n".join(json.dumps(row) for row in records))
    # Uncommitted observations cannot advance the durable worker checkpoint.
    assert not process_batch(repository, collector)
    repository.execute(
        "INSERT INTO ingestion_batches SETTINGS date_time_input_format='best_effort' "
        "FORMAT JSONEachRow\n"
        + json.dumps(
            {
                "collector_id": str(collector),
                "batch_id": 1,
                "row_count": 16,
                "committed_at": observations[-1]["received_at"],
            }
        )
    )
    assert process_batch(repository, collector)
    assert not process_batch(repository, collector)
    market = Market.objects.get()
    assert len(repository.batch(collector, 1)) == 16
    assert market.metrics == analyze(observations)[0]
    # Analyst cutoffs exclude late-recorded data; collector replay still sees every input.
    window = {"start": observations[0]["received_at"], "end": observations[-1]["recorded_at"]}
    assert len(repository.history(market.id, **window)) == 16
    assert (
        len(repository.history(market.id, **window, known_at=observations[5]["recorded_at"])) == 6
    )
    signals = repository.signals(market.id)
    assert len(signals) == 3
    repository.save_signals(signals)
    assert len(repository.signals(market.id)) == 3
    for signal in signals:
        evidence = repository.signal_inputs(signal)
        recomputed = analyze(evidence)[1]
        assert signal in recomputed


def test_recent_signal_feed_filters_source_type_and_time(repository):
    from quanthecy_analytics.signals import analyze

    observations = json.loads((Path(__file__).parent / "fixtures/research-window.json").read_text())
    now = datetime.now(UTC).isoformat()
    market_id = observations[-1]["market"]["id"]
    repository.execute(
        "INSERT INTO market_observations (market_id, platform, received_at) "
        "SETTINGS date_time_input_format='best_effort' FORMAT JSONEachRow\n"
        + json.dumps({"market_id": market_id, "platform": "polymarket", "received_at": now})
    )
    signals = analyze(observations)[1]
    repository.save_signals(signals)
    assert repository.recent_signals(platform=None, signal_type=None, limit=100) == []
    for signal in signals:
        signal["received_at"] = now
        signal["id"] = str(uuid4())
    repository.save_signals(signals)
    assert len(repository.recent_signals(platform="polymarket", signal_type=None, limit=100)) == 3
    assert repository.recent_signals(platform="kalshi", signal_type=None, limit=100) == []
    selected = repository.recent_signals(platform=None, signal_type="PROBABILITY_SPIKE", limit=1)
    assert len(selected) == 1 and selected[0]["signal_type"] == "PROBABILITY_SPIKE"


def test_raw_cleanup_preserves_envelopes_signals_and_next_batch(repository):
    from django.utils import timezone
    from quanthecy.accounts.models import User
    from quanthecy.operations.models import RawPayloadDeletion
    from quanthecy.operations.raw_data import enqueue_deletion, preview_deletion, process_deletion
    from quanthecy_analytics.signals import analyze
    from quanthecy_analytics.storage.raw import RawDataRepository, RawScope, RawWindow

    observations = json.loads((Path(__file__).parent / "fixtures/research-window.json").read_text())
    collector = uuid4()
    for batch_id, batch in enumerate([observations[:6], observations[6:12], observations[12:]], 1):
        records = [
            {
                "collector_id": str(collector),
                "batch_id": batch_id,
                "observation_id": row["observation_id"],
                "platform": row["platform"],
                "market_id": row["market"]["id"],
                "outcome_id": row["outcome"]["id"],
                "received_at": row["received_at"],
                "envelope": json.dumps(row),
                "raw_payload": json.dumps({"exchange_field": "original", "batch": batch_id}),
            }
            for row in batch
        ]
        repository.execute(
            "INSERT INTO market_observations SETTINGS date_time_input_format='best_effort' "
            "FORMAT JSONEachRow\n" + "\n".join(json.dumps(row) for row in records)
        )
        repository.execute(
            "INSERT INTO ingestion_batches SETTINGS date_time_input_format='best_effort' "
            "FORMAT JSONEachRow\n"
            + json.dumps(
                {
                    "collector_id": str(collector),
                    "batch_id": batch_id,
                    "row_count": len(batch),
                    "committed_at": batch[-1]["received_at"],
                }
            )
        )
    assert process_batch(repository, collector)
    assert process_batch(repository, collector)
    market = Market.objects.get()
    raw = RawDataRepository(repository)
    window = RawWindow(
        platform="polymarket",
        market_id=market.pk,
        start=observations[0]["received_at"],
        end=datetime.fromisoformat(observations[-1]["received_at"]) + timedelta(seconds=1),
    )
    assert len(raw.observations(window)) == 16
    first_id = observations[0]["observation_id"]
    assert raw.observation(market.pk, first_id)["raw_payload"]
    operator = User.objects.create_superuser("cleanup@example.com", "test-password")
    with patch("quanthecy.operations.raw_data.repository", return_value=raw):
        summary, token = preview_deletion(operator, window)
    assert summary == {"observations": 16, "eligible": 6, "protected": 10, "cleared": 0}
    job = enqueue_deletion(operator, token, "Integration cleanup")
    scope = RawScope.model_validate(job.scope)
    assert process_deletion(raw)
    # Mutation commands must retain the operation UUID for uncertain-submit recovery.
    assert raw.mutation_status(job.pk)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        RawPayloadDeletion.objects.filter(pk=job.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        process_deletion(raw)
        job.refresh_from_db()
        if job.state != "RUNNING":
            break
        time.sleep(0.1)
    assert job.state == "SUCCEEDED", (job.error_code, raw.mutation_status(job.pk))
    assert raw.summary(scope) == {"observations": 16, "eligible": 0, "protected": 10, "cleared": 6}
    detail = raw.observation(market.pk, first_id)
    assert detail["raw_payload"] == ""
    assert json.loads(detail["envelope"]) == observations[0]
    assert repository.batch(collector, 1) == observations[:6]
    assert process_batch(repository, collector)  # Batch 3 still advances normally after clearing.
    assert not process_batch(repository, collector)
    market.refresh_from_db()
    assert market.metrics == analyze(observations)[0]
    for signal in repository.signals(market.pk):
        assert signal in analyze(repository.signal_inputs(signal))[1]
    # A replay of the same frozen deletion cannot expand to the newly reconciled batch.
    raw.submit_deletion(job.pk, scope)
    assert raw.summary(scope)["protected"] == 10


def test_catalog_page_replay_reconciles_once_without_price_history(repository):
    from quanthecy.markets.catalog import run_catalog_ingestion
    from quanthecy.markets.models import CatalogMarket
    from quanthecy.markets.selection import market_id

    collector = uuid4()
    at = datetime.now(UTC).isoformat()
    page = {
        "schema_version": 1,
        "page_id": 1,
        "platform": "polymarket",
        "observed_at": at,
        "scan_id": str(uuid4()),
        "pages": 1,
        "rows_seen": 1,
        "accepted": 1,
        "skipped": 0,
        "state": "complete",
        "items": [
            {
                "id": str(market_id("polymarket", "123")),
                "exchange_id": "123",
                "title": "Directory only",
                "status": "OPEN",
                "closes_at": None,
                "volume_24h": 12.0,
                "volume_unit": "USD",
            }
        ],
    }
    row = {
        "collector_id": str(collector),
        "page_id": 1,
        "received_at": at,
        "envelope": json.dumps(page),
    }
    for _ in range(2):
        repository.execute(
            "INSERT INTO market_catalog_pages SETTINGS date_time_input_format='best_effort' "
            "FORMAT JSONEachRow\n" + json.dumps(row)
        )
    assert run_catalog_ingestion(repository) == 1
    assert run_catalog_ingestion(repository) == 0
    assert CatalogMarket.objects.count() == 1
    assert not Market.objects.exists()


def test_paper_execution_quotes_are_deduplicated_and_cannot_see_future_data(repository):
    from quanthecy.paper.repository import ExecutionRepository
    from quanthecy_analytics.paper import ExecutionQuote

    now = datetime(2026, 9, 18, 12, tzinfo=UTC)
    mid = uuid4()
    q = ExecutionQuote(
        schema_version=1,
        quote_id=uuid4(),
        market_id=mid,
        platform="polymarket",
        exchange_id="123",
        outcome_id="456",
        received_at=now - timedelta(seconds=10),
        recorded_at=now - timedelta(seconds=10),
        metadata_at=now - timedelta(seconds=10),
        source_at=None,
        status="OPEN",
        settlement=None,
        bids=[{"price": "0.49", "size": "100"}],
        asks=[{"price": "0.50", "size": "100"}],
        fee_rate="0",
        fee_model="polymarket_quadratic",
        fee_source="fixture",
        source="fixture",
    )

    def insert(quote):
        row = dict(
            quote_id=str(quote.quote_id),
            market_id=str(mid),
            platform=quote.platform,
            received_at=quote.received_at.isoformat(),
            envelope=quote.model_dump_json(),
        )
        repository.execute(
            "INSERT INTO execution_quotes SETTINGS date_time_input_format='best_effort' "
            "FORMAT JSONEachRow\n"
            + json.dumps(row)
        )

    insert(q)
    insert(q)
    reader = ExecutionRepository(repository)
    assert reader.latest([mid], now)[mid].quote_id == q.quote_id
    assert repository.rows("SELECT count() AS n FROM execution_quotes FINAL")[0]["n"] == 1
    future = q.model_copy(
        update={
            "quote_id": uuid4(),
            "received_at": now + timedelta(seconds=2),
            "recorded_at": now + timedelta(seconds=2),
        }
    )
    insert(future)
    assert reader.latest([mid], now)[mid].quote_id == q.quote_id
    assert reader.latest([mid], now + timedelta(seconds=3))[mid].quote_id == future.quote_id
    delayed = q.model_copy(
        update={
            "quote_id": uuid4(),
            "received_at": now - timedelta(seconds=1),
            "recorded_at": now + timedelta(seconds=5),
        }
    )
    insert(delayed)
    assert reader.latest([mid], now) == {}  # Fail closed if persistence is in the future.
