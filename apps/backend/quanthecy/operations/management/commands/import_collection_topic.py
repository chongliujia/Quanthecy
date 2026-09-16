"""Initialize managed collection without replacing previously collected markets."""

from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as SchemaError

from quanthecy.accounts.models import User
from quanthecy.markets.models import CollectionTarget, Market, ResearchTopic
from quanthecy.markets.selection import lock_plan, record_change, validate_candidate
from quanthecy.operations.policies import require_operator


class TargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str
    exchange_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=2000)


class TopicInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9-]{1,50}$")
    name: str = Field(min_length=1, max_length=120)
    name_zh: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    description_zh: str = Field(default="", max_length=2000)
    targets: list[TargetInput] = Field(min_length=1, max_length=100)


class Command(BaseCommand):
    help = "Import a curated topic, preserving existing targets and operator edits."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("manifest")
        parser.add_argument(
            "--actor", required=True, help="Operator email, recorded as a UUID in audit events"
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        try:
            source = Path(options["manifest"])
            if source.stat().st_size > 256_000:
                raise CommandError("Topic manifest is too large")
            value = TopicInput.model_validate_json(source.read_text())
            actor = User.objects.get(email__iexact=options["actor"])
            for permission in ("markets.add_researchtopic", "markets.add_collectiontarget"):
                require_operator(actor, permission)
            plan = lock_plan()
            was_managed = plan.managed
            changes = []
            if not plan.managed:
                baseline, baseline_created = ResearchTopic.objects.get_or_create(
                    slug="existing-coverage",
                    defaults={
                        "name": "Existing collection",
                        "name_zh": "原有采集范围",
                        "is_public": False,
                        "description": "Targets retained when managed collection was activated.",
                        "description_zh": "启用后台管理时保留的原有采集名单。",
                    },
                )
                if baseline_created:
                    changes.append(str(baseline.id))
                # Refuse an oversized import instead of silently dropping prior coverage.
                if Market.objects.count() > 100:
                    raise CommandError(
                        "More than 100 markets; curate a bounded baseline before activation."
                    )
                for market in Market.objects.all():
                    retained_target, created = CollectionTarget.objects.get_or_create(
                        topic=baseline,
                        platform=market.platform,
                        exchange_id=market.exchange_id,
                        defaults={
                            "label": market.title[:300],
                            "rationale": "Preserved existing collection on activation.",
                        },
                    )
                    if created:
                        changes.append(str(retained_target.id))
                baseline.full_clean()
                plan.managed = True
            topic, created = ResearchTopic.objects.get_or_create(
                slug=value.slug,
                defaults=value.model_dump(exclude={"targets", "slug"}),
            )
            if created:
                changes.append(str(topic.id))
            topic.full_clean()
            for item in value.targets:
                target, created = CollectionTarget.objects.get_or_create(
                    topic=topic,
                    platform=item.platform,
                    exchange_id=item.exchange_id,
                    defaults=item.model_dump(exclude={"platform", "exchange_id"}),
                )
                target.full_clean()
                if created:
                    changes.append(str(target.id))
            validate_candidate()
            if changes or not was_managed:
                record_change(
                    plan,
                    actor,
                    topic.id,
                    "Initialize curated research coverage; preserve previous targets.",
                    {"created_ids": changes, "topic": topic.slug},
                )
            self.stdout.write(
                f"Topic {topic.slug}; {len(changes)} new records; managed revision {plan.revision}"
            )
        except (OSError, SchemaError, ValidationError, User.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
