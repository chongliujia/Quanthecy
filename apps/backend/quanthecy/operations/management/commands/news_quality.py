"""Read-only, bounded collection and discovery quality snapshot."""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from quanthecy.research.discovery import discover
from quanthecy.research.events import definitions
from quanthecy.research.models import EvidenceSource
from quanthecy.research.services import source_value, visible_evidence


class Command(BaseCommand):
    help = "Report latest poll quality and content-match share in up to 100 saved items per source."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--event", default="fed-october-2026")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        definition = definitions(now).filter(event__slug=options["event"]).first()
        if not definition:
            raise CommandError("No visible event definition for this slug.")
        sources = []
        for source in EvidenceSource.objects.order_by("slug"):
            revisions = list(
                visible_evidence(now)
                .filter(item__source=source)
                .order_by("-observed_at", "id")[:100]
            )
            matching = sum(discover(definition, r) is not None for r in revisions)
            total = (
                source.last_entry_count + source.last_rejected_count + source.last_duplicate_count
            )
            sources.append(
                {
                    "source": source.slug,
                    "status": source_value(source).status,
                    "last_checked_at": source.last_checked_at.isoformat()
                    if source.last_checked_at
                    else None,
                    "latest_poll": {
                        "accepted": source.last_entry_count,
                        "rejected": source.last_rejected_count,
                        "duplicates": source.last_duplicate_count,
                        "undated": source.last_undated_count,
                        "duplicate_share": source.last_duplicate_count / total if total else None,
                    },
                    "saved_sample_size": len(revisions),
                    "discovery_matches": matching,
                    "discovery_match_share": matching / len(revisions) if revisions else None,
                }
            )
        self.stdout.write(
            json.dumps(
                {
                    "observed_at": now.isoformat(),
                    "event": options["event"],
                    "definition_version": definition.version,
                    "policy": definition.discovery_policy,
                    "sample_limit_per_source": 100,
                    "sources": sources,
                },
                indent=2,
            )
        )
