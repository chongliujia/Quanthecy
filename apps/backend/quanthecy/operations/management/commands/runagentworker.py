import logging
import signal
from pathlib import Path
from threading import Event, Thread
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from quanthecy.agents.worker import process_one

logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/quanthecy-agent-heartbeat")


class Command(BaseCommand):
    help = "Run bounded, on-demand Agent jobs. No automatic model calls or retries."

    def handle(self, *args: Any, **options: Any) -> None:
        stopped = Event()

        def stop(signum: int, frame: FrameType | None) -> None:
            stopped.set()

        def heartbeat() -> None:
            while not stopped.is_set():
                HEARTBEAT.touch()
                stopped.wait(10)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            while not stopped.is_set():
                close_old_connections()
                try:
                    worked = process_one(stopped)
                except Exception:
                    logger.error("Agent worker cycle failed; unfinished leases will expire.")
                    worked = False
                if not worked:
                    stopped.wait(2)
        finally:
            stopped.set()
            thread.join(timeout=2)
            HEARTBEAT.unlink(missing_ok=True)
            close_old_connections()
