import json
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import transaction
from quanthecy_analytics.contracts.validation import validate_observation
from quanthecy_analytics.signals import analyze
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository

from .models import Event, IngestionCheckpoint, Market, Outcome


def validate_identity(observation: dict[str, Any]) -> None:
    for kind in ("event", "market", "outcome"):
        entity = observation[kind]
        expected = uuid5(
            NAMESPACE_URL,
            f"https://quanthecy.org/identity/v1/{observation['platform']}/{kind}/{entity['exchange_id']}",
        )
        if UUID(entity["id"]) != expected:
            raise ValueError("Collector identity mapping does not match identity/v1")


def reconcile(observation: dict[str, Any], metrics: dict[str, Any]) -> None:
    validate_identity(observation)
    observed = datetime.fromisoformat(observation["received_at"])
    event, _ = Event.objects.get_or_create(
        id=observation["event"]["id"],
        defaults={
            "platform": observation["platform"],
            "exchange_id": observation["event"]["exchange_id"],
            "title": observation["event"]["title"],
            "observed_at": observed,
        },
    )
    Event.objects.filter(id=event.id, observed_at__lte=observed).update(
        title=observation["event"]["title"], observed_at=observed
    )
    defaults = {
        "event": event,
        "platform": observation["platform"],
        "exchange_id": observation["market"]["exchange_id"],
        "title": observation["market"]["title"],
        "status": observation["market"]["status"],
        "first_observed_at": observed,
        "last_observed_at": observed,
        "latest": observation,
        "metrics": metrics,
        "probability_change_15m": metrics.get("probability_change_15m"),
        "volume_zscore": metrics.get("volume_zscore"),
    }
    market, created = Market.objects.get_or_create(
        id=observation["market"]["id"], defaults=defaults
    )
    # PostgreSQL serializes metadata updates across independent collector checkpoints.
    market = Market.objects.select_for_update().get(id=market.id)
    if observed < market.first_observed_at:
        market.first_observed_at = observed
        market.save(update_fields=["first_observed_at"])
    if created or observed >= market.last_observed_at:
        defaults.pop("first_observed_at")
        Market.objects.filter(id=market.id).update(**defaults)
        Outcome.objects.update_or_create(
            id=observation["outcome"]["id"],
            defaults={
                "market": market,
                "exchange_id": observation["outcome"]["exchange_id"],
                "label": observation["outcome"]["label"],
                "result": observation["outcome"]["result"],
            },
        )


def process_batch(repository: ClickHouseRepository, collector: UUID) -> bool:
    IngestionCheckpoint.objects.get_or_create(collector_id=collector)
    with transaction.atomic():
        checkpoint = IngestionCheckpoint.objects.select_for_update().get(collector_id=collector)
        batch = repository.next_batch(collector, checkpoint.batch_id)
        if batch is None:
            return False
        if int(batch["batch_id"]) != checkpoint.batch_id + 1:
            raise ValueError("Missing committed collector batch; checkpoint held")
        rows = repository.batch(collector, int(batch["batch_id"]))
        if len(rows) != int(batch["row_count"]):
            raise ValueError("Incomplete committed batch; checkpoint held")
        for row in rows:
            validate_observation(json.dumps(row))
            end = datetime.fromisoformat(row["received_at"])
            history = repository.history(
                UUID(row["market"]["id"]),
                start=(end - timedelta(minutes=20)).isoformat(),
                end=end.isoformat(),
                limit=1000,
            )
            metrics, signals = analyze(history)
            repository.save_signals(signals)
            reconcile(row, metrics)
        checkpoint.batch_id = int(batch["batch_id"])
        checkpoint.save(update_fields=["batch_id", "updated_at"])
    return True


def run_ingestion(repository: ClickHouseRepository) -> int:
    processed = 0
    for collector in repository.collectors():
        for _ in range(5):
            if not process_batch(repository, collector):
                break
            processed += 1
    return processed
