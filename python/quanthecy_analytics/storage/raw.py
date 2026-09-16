"""Bounded operator access to ClickHouse; never delete observation rows or batch markers."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from .clickhouse import ClickHouseRepository


class RawWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["polymarket", "kalshi"]
    market_id: UUID | None = None
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def bounded(self) -> "RawWindow":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Use timezone-aware timestamps.")
        if self.start >= self.end or self.end - self.start > timedelta(days=7):
            raise ValueError("Choose an increasing window of at most seven days.")
        self.start = self.start.astimezone(UTC)
        self.end = self.end.astimezone(UTC)
        return self


class RawScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: RawWindow
    checkpoints: dict[UUID, int]

    @model_validator(mode="after")
    def bounded(self) -> "RawScope":
        if len(self.checkpoints) > 100 or any(
            type(batch) is not int or not 0 <= batch < 2**64 for batch in self.checkpoints.values()
        ):
            raise ValueError("Invalid collector checkpoints.")
        return self


def window_filter(window: RawWindow) -> tuple[str, dict[str, Any]]:
    return (
        "platform = {platform:String} "
        "AND received_at >= parseDateTime64BestEffort({start:String}, 6, 'UTC') "
        "AND received_at < parseDateTime64BestEffort({end:String}, 6, 'UTC') "
        + ("AND market_id = {market:UUID} " if window.market_id else ""),
        {
            "platform": window.platform,
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            **({"market": window.market_id} if window.market_id else {}),
        },
    )


def eligible_filter(scope: RawScope) -> tuple[str, dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {}
    for i, (collector, batch) in enumerate(sorted(scope.checkpoints.items())):
        # Strictly older than the reconciled batch: the collector has already advanced
        # its durable journal beyond these payloads, so normal replay cannot restore them.
        clauses.append(f"(collector_id = {{collector{i}:UUID}} AND batch_id < {{batch{i}:UInt64}})")
        params.update({f"collector{i}": collector, f"batch{i}": batch})
    return "(" + (" OR ".join(clauses) or "0") + ")", params


class RawDataRepository:
    def __init__(self, history: ClickHouseRepository) -> None:
        self.history = history

    def observations(self, window: RawWindow, *, offset: int = 0) -> list[dict[str, Any]]:
        if not 0 <= offset <= 5000:
            raise ValueError("Choose a narrower window after 5,000 observations.")
        where, params = window_filter(window)
        return self.history.rows(
            "SELECT observation_id, market_id, collector_id, batch_id, platform, "
            "received_at, "
            "JSONExtractString(envelope, 'market', 'title') AS title, "
            "quality_flags, length(raw_payload) AS raw_bytes "
            f"FROM market_observations FINAL WHERE {where} "
            "ORDER BY received_at DESC, observation_id DESC LIMIT 51 OFFSET {offset:UInt32}",
            {**params, "offset": offset},
        )

    def observation(self, market_id: UUID, observation_id: UUID) -> dict[str, Any] | None:
        rows = self.history.rows(
            "SELECT observation_id, market_id, collector_id, batch_id, platform, "
            "received_at, lengthUTF8(raw_payload) AS raw_length, "
            "lengthUTF8(envelope) AS envelope_length, "
            "substringUTF8(raw_payload, 1, 131072) AS raw_payload, "
            "substringUTF8(envelope, 1, 131072) AS envelope "
            "FROM market_observations FINAL "
            "WHERE market_id = {market:UUID} AND observation_id = {observation:UUID} LIMIT 1",
            {"market": market_id, "observation": observation_id},
        )
        return rows[0] if rows else None

    def summary(self, scope: RawScope) -> dict[str, int]:
        where, params = window_filter(scope.window)
        eligible, checkpoints = eligible_filter(scope)
        row = self.history.rows(
            "SELECT count() AS observations, "
            f"countIf(raw_payload != '' AND {eligible}) AS eligible, "
            f"countIf(raw_payload != '' AND NOT {eligible}) AS protected, "
            "countIf(raw_payload = '') AS cleared "
            f"FROM market_observations FINAL WHERE {where}",
            {**params, **checkpoints},
        )[0]
        return {key: int(value) for key, value in row.items()}

    def mutation_status(self, operation_id: UUID) -> list[dict[str, Any]]:
        return self.history.rows(
            "SELECT mutation_id, is_done, parts_to_do, latest_fail_reason != '' AS has_failure "
            "FROM system.mutations WHERE database = {database:String} "
            "AND table = 'market_observations' AND position(command, {operation:String}) > 0",
            {"database": self.history.database, "operation": str(operation_id)},
        )

    def submit_deletion(self, operation_id: UUID, scope: RawScope) -> None:
        where, params = window_filter(scope.window)
        eligible, checkpoints = eligible_filter(scope)
        # substring(uuid, 1, 0) is the empty string. Keeping the operation UUID in
        # the mutation expression makes submissions discoverable after a lost HTTP reply.
        self.history.execute(
            "ALTER TABLE market_observations "
            "UPDATE raw_payload = substring({operation:String}, 1, 0) "
            f"WHERE {where} AND {eligible} AND raw_payload != '' SETTINGS mutations_sync=0",
            {**params, **checkpoints, "operation": str(operation_id)},
        )

    def collector_batches(self) -> list[dict[str, Any]]:
        return self.history.rows(
            "SELECT collector_id, max(batch_id) AS latest_batch "
            "FROM ingestion_batches GROUP BY collector_id ORDER BY collector_id LIMIT 101"
        )
