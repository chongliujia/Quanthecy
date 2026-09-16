from django.conf import settings
from django.db import connection
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository
from redis import Redis


def dependency_status() -> dict[str, bool]:
    status = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        status["postgres"] = True
    except Exception:
        status["postgres"] = False
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=3, socket_timeout=3
        ) as redis:
            status["redis"] = bool(redis.ping())
    except Exception:
        status["redis"] = False
    try:
        status["clickhouse"] = ClickHouseRepository(
            url=settings.CLICKHOUSE_URL,
            database=settings.CLICKHOUSE_DATABASE,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
        ).ready()
    except Exception:
        status["clickhouse"] = False
    return status
