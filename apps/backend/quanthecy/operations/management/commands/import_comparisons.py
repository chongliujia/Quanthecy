import json
from pathlib import Path
from typing import Any, Literal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quanthecy.markets.models import Market
from quanthecy.research.models import Comparison, ComparisonReview
from quanthecy.research.reviews import append_review


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["polymarket", "kalshi"]
    exchange_id: str
    rules_version: str


class ReviewedPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    title: str
    left: Selection
    right: Selection
    relation: Literal["EQUIVALENT", "RELATED", "INCOMPATIBLE"]
    alignment: Literal["SAME", "COMPLEMENT"] = "SAME"
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str
    differences: str
    reviewer_label: str


class Command(BaseCommand):
    help = "Import explicitly reviewed comparison manifests; validate frozen rule hashes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("file")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        try:
            raw = json.loads(Path(options["file"]).read_text())
            if not isinstance(raw, list) or len(raw) > 100:
                raise ValueError("Expected a list of at most 100 reviewed pairs")
            rows = [ReviewedPair.model_validate(row) for row in raw]
            for row in rows:
                left, right = [
                    Market.objects.get(platform=s.platform, exchange_id=s.exchange_id)
                    for s in (row.left, row.right)
                ]
                pair, created = Comparison.objects.get_or_create(
                    slug=row.slug, defaults={"left": left, "right": right}
                )
                pair = Comparison.objects.select_for_update().get(pk=pair.pk)
                locked = {
                    m.pk: m
                    for m in Market.objects.select_for_update()
                    .filter(pk__in=[left.pk, right.pk])
                    .order_by("pk")
                }
                left, right = locked[left.pk], locked[right.pk]
                if [
                    left.latest["market"]["rules_version"],
                    right.latest["market"]["rules_version"],
                ] != [row.left.rules_version, row.right.rules_version]:
                    raise ValueError("Market rules changed since source review. Review again.")
                if pair.left_id != left.pk or pair.right_id != right.pk:
                    raise ValueError("An existing pair cannot change endpoints")
                if created:
                    pair.full_clean()
                values = row.model_dump(exclude={"slug", "left", "right"})
                previous = pair.reviews.order_by("-version").first()
                if (
                    previous
                    and all(getattr(previous, key) == value for key, value in values.items())
                    and [
                        previous.left_snapshot["market"]["rules_version"],
                        previous.right_snapshot["market"]["rules_version"],
                    ]
                    == [row.left.rules_version, row.right.rules_version]
                ):
                    self.stdout.write(f"Unchanged: {row.slug}")
                    continue
                append_review(
                    ComparisonReview(comparison=pair, **values),
                    [row.left.rules_version, row.right.rules_version],
                )
                self.stdout.write(f"Reviewed: {row.slug}")
        except (
            OSError,
            ValueError,
            ValidationError,
            DjangoValidationError,
            Market.DoesNotExist,
        ) as exc:
            raise CommandError(str(exc)) from exc
