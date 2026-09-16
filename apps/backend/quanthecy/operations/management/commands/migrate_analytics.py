from typing import Any

from django.core.management.base import BaseCommand
from quanthecy_analytics.storage.migrate import migrate

from quanthecy.markets.repositories import history_repository


class Command(BaseCommand):
    help = "Apply checksum-verified ClickHouse migrations (safe to retry)."

    def handle(self, *args: Any, **options: Any) -> None:
        for version in migrate(history_repository()):
            self.stdout.write(f"Applied {version}")
