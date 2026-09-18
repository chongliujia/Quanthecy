import logging
import signal
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from quanthecy.paper.worker import run_once

logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/quanthecy-paper-heartbeat")


class Command(BaseCommand):
    help = "Run virtual paper accounts against persisted public order books."

    def handle(self, *args: Any, **options: Any) -> None:
        stopped = Event()

        def stop(signum: int, frame: FrameType | None) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            while not stopped.is_set():
                close_old_connections()
                try:
                    run_once()
                    HEARTBEAT.touch()
                except Exception:
                    HEARTBEAT.unlink(missing_ok=True)
                    logger.exception("Paper worker unavailable; no simulated orders executed")
                stopped.wait(5)
        finally:
            HEARTBEAT.unlink(missing_ok=True)
            close_old_connections()
