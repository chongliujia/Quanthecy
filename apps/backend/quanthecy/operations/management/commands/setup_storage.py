from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Apply PostgreSQL and ClickHouse migrations before application startup."

    def handle(self, *args: Any, **options: Any) -> None:
        call_command("migrate", interactive=False)
        call_command("migrate_analytics")
