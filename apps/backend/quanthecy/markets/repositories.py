from django.conf import settings
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository


def history_repository() -> ClickHouseRepository:
    return ClickHouseRepository(
        url=settings.CLICKHOUSE_URL,
        database=settings.CLICKHOUSE_DATABASE,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
    )
