"""Optional real-ClickHouse checks; create/drop only a unique test-owned database."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
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
        user="quanthecy",
        password="quanthecy-dev-only",
    )
    admin.execute(f"CREATE DATABASE {database}")
    repo = ClickHouseRepository(
        url=admin.url, database=database, user=admin.user, password=admin.password
    )
    try:
        assert migrate(repo) == ["0001_market_history"]
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
