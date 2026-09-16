import json
import logging
import signal
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from quanthecy.markets.ingestion import run_ingestion
from quanthecy.markets.repositories import history_repository
from quanthecy.markets.selection import publish_selection
from quanthecy.operations.dependencies import dependency_status

logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/quanthecy-worker-heartbeat")


class Command(BaseCommand):
    help = "Reconcile durable market batches and compute deterministic signals."

    def handle(self, *args: Any, **options: Any) -> None:
        stopped = Event()

        def stop(signum: int, frame: FrameType | None) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            while not stopped.is_set():
                close_old_connections()
                dependencies = dependency_status()
                if dependencies["postgres"]:
                    try:
                        publish_selection()
                    except Exception:
                        logger.exception(
                            "Collection plan publication failed; collector retains last good plan"
                        )
                batches = 0
                if dependencies["postgres"] and dependencies["clickhouse"]:
                    try:
                        batches = run_ingestion(history_repository())
                        HEARTBEAT.touch()
                    except Exception:
                        logger.exception("Market worker batch failed; checkpoint retained")
                        HEARTBEAT.unlink(missing_ok=True)
                else:
                    HEARTBEAT.unlink(missing_ok=True)
                logger.info(
                    json.dumps(
                        {
                            "service": "worker",
                            "mode": "market_analytics",
                            "dependencies": dependencies,
                            "batches_processed": batches,
                        }
                    )
                )
                stopped.wait(10)
        finally:
            HEARTBEAT.unlink(missing_ok=True)
            close_old_connections()
            logger.info('{"service":"worker","event":"shutdown"}')
