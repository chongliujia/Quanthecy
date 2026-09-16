import logging
import signal
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from quanthecy.research.news import associate_topics, initialize_sources, poll_one_source

logger = logging.getLogger(__name__)
HEARTBEAT = Path("/tmp/quanthecy-news-heartbeat")


class Command(BaseCommand):
    help = "Poll selected official news feeds independently of market analytics."

    def handle(self, *args: Any, **options: Any) -> None:
        stopped = Event()

        def stop(signum: int, frame: FrameType | None) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        initialize_sources()
        cycles = 0
        try:
            while not stopped.is_set():
                close_old_connections()
                try:
                    polled = poll_one_source()
                    if polled or cycles % 6 == 0:
                        associate_topics()
                    HEARTBEAT.touch()
                except Exception:
                    logger.exception("News worker cycle failed")
                    HEARTBEAT.unlink(missing_ok=True)
                cycles += 1
                stopped.wait(10)
        finally:
            HEARTBEAT.unlink(missing_ok=True)
            close_old_connections()
