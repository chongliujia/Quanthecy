import logging
import signal
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from quanthecy.operations.raw_data import process_deletion

logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/quanthecy-maintenance-heartbeat")


class Command(BaseCommand):
    help = "Process operator-requested raw JSON cleanup independently of ingestion."

    def handle(self, *args: Any, **options: Any) -> None:
        stopped = Event()

        def stop(signum: int, frame: FrameType | None) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            while not stopped.is_set():
                HEARTBEAT.touch()
                close_old_connections()
                try:
                    worked = process_deletion()
                except Exception:
                    logger.error("Maintenance cycle failed; unfinished leases will expire.")
                    worked = False
                stopped.wait(2 if worked else 10)
        finally:
            HEARTBEAT.unlink(missing_ok=True)
            close_old_connections()
