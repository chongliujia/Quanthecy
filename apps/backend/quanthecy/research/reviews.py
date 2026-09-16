from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from quanthecy.markets.models import Market

from .models import Comparison, ComparisonReview


def snapshot(market: Market) -> dict[str, Any]:
    row = market.latest
    if not row or not row["market"]["resolution_rules"] or not row["market"]["rules_version"]:
        raise ValidationError("Collect both markets and their resolution rules before review.")
    return {
        "platform": market.platform,
        "exchange_id": market.exchange_id,
        "market": row["market"],
        "outcome": row["outcome"],
        "source": row["provenance"]["source"],
        "observation_id": row["observation_id"],
    }


@transaction.atomic
def append_review(review: ComparisonReview, expected_rules: list[str] | None = None) -> None:
    pair = Comparison.objects.select_for_update().get(pk=review.comparison_id)
    # Lock metadata during capture; ingestion updates these same rows transactionally.
    markets = {
        m.id: m
        for m in Market.objects.select_for_update()
        .filter(id__in=[pair.left_id, pair.right_id])
        .order_by("id")
    }
    left, right = markets[pair.left_id], markets[pair.right_id]
    if left.platform == right.platform:
        raise ValidationError("Choose markets on different platforms.")
    review.left_snapshot, review.right_snapshot = snapshot(left), snapshot(right)
    if expected_rules and expected_rules != [
        review.left_snapshot["market"]["rules_version"],
        review.right_snapshot["market"]["rules_version"],
    ]:
        raise ValidationError("Market rules changed since the source review. Review again.")
    review.version = (
        pair.reviews.order_by("-version").values_list("version", flat=True).first() or 0
    ) + 1
    review.reviewed_at = timezone.now()
    review.full_clean()
    review.save()
