from datetime import datetime
from uuid import UUID

from quanthecy_analytics.paper import ExecutionQuote
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository

from quanthecy.markets.repositories import history_repository


class ExecutionRepository:
    def __init__(self, storage: ClickHouseRepository | None = None) -> None:
        self.storage = storage or history_repository()

    def latest(self, ids: list[UUID], now: datetime) -> dict[UUID, ExecutionQuote]:
        if not ids:
            return {}
        if len(ids) > 20:
            raise ValueError("Execution universe exceeds 20 markets")
        rows = self.storage.rows(
            "SELECT argMax(envelope, (received_at, quote_id)) AS envelope "
            "FROM execution_quotes FINAL WHERE market_id IN {ids:Array(UUID)} "
            "AND received_at >= parseDateTime64BestEffort({now:String}, 6, 'UTC') "
            "- INTERVAL 5 MINUTE "
            "AND received_at <= parseDateTime64BestEffort({now:String}, 6, 'UTC') "
            "GROUP BY market_id",
            {"ids": "[" + ",".join(f"'{value}'" for value in ids) + "]", "now": now.isoformat()},
        )
        result = {}
        for row in rows:
            quote = ExecutionQuote.model_validate_json(row["envelope"])
            if quote.market_id not in ids or quote.recorded_at > now:
                continue
            result[quote.market_id] = quote
        return result
