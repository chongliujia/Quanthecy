import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID


class AnalyticsUnavailable(Exception):
    pass


class ClickHouseRepository:
    """Explicit analytical repository with bound query parameters and bounded reads."""

    def __init__(self, *, url: str, database: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.user = user
        self.password = password

    def execute(
        self, sql: str, params: dict[str, Any] | None = None, *, timeout: int = 15
    ) -> bytes:
        query = {"database": self.database, "wait_end_of_query": "1", "max_execution_time": "10"}
        query.update({f"param_{key}": str(value) for key, value in (params or {}).items()})
        request = Request(
            f"{self.url}/?{urlencode(query)}",
            data=sql.encode(),
            method="POST",
            headers={"X-ClickHouse-User": self.user, "X-ClickHouse-Key": self.password},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, ValueError) as exc:
            raise AnalyticsUnavailable("Historical data is temporarily unavailable.") from exc

    def ready(self) -> bool:
        return self.execute("SELECT 1", timeout=3).strip() == b"1"

    def rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in self.execute(sql + " FORMAT JSONEachRow", params).splitlines()
        ]

    def collectors(self) -> list[UUID]:
        return [
            UUID(row["collector_id"])
            for row in self.rows("SELECT DISTINCT collector_id FROM ingestion_batches LIMIT 100")
        ]

    def next_batch(self, collector: UUID, after: int) -> dict[str, Any] | None:
        rows = self.rows(
            "SELECT batch_id, row_count FROM ingestion_batches FINAL "
            "WHERE collector_id = {collector:UUID} AND batch_id > {after:UInt64} "
            "ORDER BY batch_id LIMIT 1",
            {"collector": collector, "after": after},
        )
        return rows[0] if rows else None

    def batch(self, collector: UUID, batch_id: int) -> list[dict[str, Any]]:
        return [
            json.loads(row["envelope"])
            for row in self.rows(
                "SELECT envelope FROM market_observations FINAL "
                "WHERE collector_id = {collector:UUID} AND batch_id = {batch:UInt64} "
                "ORDER BY received_at, observation_id LIMIT 101",
                {"collector": collector, "batch": batch_id},
            )
        ]

    def history(
        self,
        market: UUID,
        *,
        start: str,
        end: str,
        limit: int = 1000,
        descending: bool = False,
        known_at: str | None = None,
    ) -> list[dict[str, Any]]:
        direction = "DESC" if descending else "ASC"
        return [
            json.loads(row["envelope"])
            for row in self.rows(
                "SELECT envelope FROM market_observations FINAL "
                "WHERE market_id = {market:UUID} "
                "AND received_at >= parseDateTime64BestEffort({start:String}, 6, 'UTC') "
                "AND received_at <= parseDateTime64BestEffort({end:String}, 6, 'UTC') "
                + (
                    "AND parseDateTime64BestEffort(JSONExtractString(envelope, 'recorded_at'), "
                    "6, 'UTC') <= parseDateTime64BestEffort({known:String}, 6, 'UTC') "
                    if known_at
                    else ""
                )
                + f"ORDER BY received_at {direction}, observation_id {direction} "
                "LIMIT {limit:UInt32}",
                {
                    "market": market,
                    "start": start,
                    "end": end,
                    "limit": limit,
                    **({"known": known_at} if known_at else {}),
                },
            )
        ]

    def save_signals(self, signals: list[dict[str, Any]]) -> None:
        if not signals:
            return
        rows = [
            {
                "signal_id": s["id"],
                "market_id": s["market_id"],
                "outcome_id": s["outcome_id"],
                "received_at": s["received_at"],
                "signal_type": s["signal_type"],
                "score": s["score"],
                "report": json.dumps(s),
            }
            for s in signals
        ]
        self.execute(
            "INSERT INTO signals SETTINGS date_time_input_format='best_effort' "
            "FORMAT JSONEachRow\n" + "\n".join(json.dumps(row) for row in rows)
        )

    def signals(
        self, market: UUID, limit: int = 50, *, cutoff: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            json.loads(row["report"])
            for row in self.rows(
                "SELECT report FROM signals FINAL WHERE market_id = {market:UUID} "
                + (
                    "AND received_at <= parseDateTime64BestEffort({cutoff:String}, 6, 'UTC') "
                    if cutoff
                    else ""
                )
                + "ORDER BY received_at DESC, signal_id LIMIT {limit:UInt32}",
                {"market": market, "limit": limit, **({"cutoff": cutoff} if cutoff else {})},
            )
        ]

    def signal(self, signal_id: UUID) -> dict[str, Any] | None:
        rows = self.rows(
            "SELECT report FROM signals FINAL WHERE signal_id = {id:UUID} LIMIT 1",
            {"id": signal_id},
        )
        return json.loads(rows[0]["report"]) if rows else None

    def recent_signals(
        self, *, platform: str | None, signal_type: str | None, limit: int
    ) -> list[dict[str, Any]]:
        # Platform is resolved from the stored observation, not inferred from UUIDs.
        return [
            json.loads(row["report"])
            for row in self.rows(
                "SELECT report FROM signals FINAL WHERE received_at >= now() - INTERVAL 7 DAY "
                "AND ({kind:String} = '' OR signal_type = {kind:String}) "
                "AND ({platform:String} = '' OR market_id IN ("
                "SELECT DISTINCT market_id FROM market_observations "
                "WHERE platform = {platform:String} "
                "AND received_at >= now() - INTERVAL 7 DAY)) "
                "ORDER BY received_at DESC, signal_id LIMIT {limit:UInt32}",
                {"kind": signal_type or "", "platform": platform or "", "limit": limit},
            )
        ]

    def signal_inputs(self, signal: dict[str, Any]) -> list[dict[str, Any]]:
        ids = [str(UUID(value)) for value in signal["observation_ids"]]
        return [
            json.loads(row["envelope"])
            for row in self.rows(
                "SELECT envelope FROM market_observations FINAL "
                "WHERE market_id = {market:UUID} AND observation_id IN {ids:Array(UUID)} "
                "ORDER BY received_at, observation_id LIMIT 1000",
                {
                    "market": signal["market_id"],
                    "ids": "[" + ",".join(f"'{value}'" for value in ids) + "]",
                },
            )
        ]

    def catalog_collectors(self) -> list[UUID]:
        return [
            UUID(row["collector_id"])
            for row in self.rows("SELECT DISTINCT collector_id FROM market_catalog_pages LIMIT 100")
        ]

    def catalog_pages(self, collector: UUID, after: int) -> list[dict[str, Any]]:
        return [
            json.loads(row["envelope"])
            for row in self.rows(
                "SELECT envelope FROM market_catalog_pages FINAL "
                "WHERE collector_id = {collector:UUID} AND page_id > {after:UInt64} "
                "ORDER BY page_id LIMIT 10",
                {"collector": collector, "after": after},
            )
        ]
