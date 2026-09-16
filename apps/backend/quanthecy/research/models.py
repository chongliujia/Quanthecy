import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AppendOnly(models.Model):
    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError("Append a new revision; historical records cannot be edited.")
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Historical research records cannot be deleted.")


class Comparison(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=160, unique=True)
    left = models.ForeignKey("markets.Market", on_delete=models.PROTECT, related_name="left_pairs")
    right = models.ForeignKey(
        "markets.Market", on_delete=models.PROTECT, related_name="right_pairs"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return self.slug

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(left=models.F("right")), name="pair_distinct"
            ),
            models.UniqueConstraint(fields=["left", "right"], name="pair_endpoints_unique"),
        ]


class ComparisonReview(AppendOnly):
    class Relation(models.TextChoices):
        EQUIVALENT = "EQUIVALENT", "Equivalent"
        RELATED = "RELATED", "Related with material differences"
        INCOMPATIBLE = "INCOMPATIBLE", "Incompatible"

    class Alignment(models.TextChoices):
        SAME = "SAME", "Same outcome"
        COMPLEMENT = "COMPLEMENT", "Complement of right outcome"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comparison = models.ForeignKey(Comparison, on_delete=models.PROTECT, related_name="reviews")
    version = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=240)
    topic = models.CharField(max_length=80, default="Macro & rates")
    relation = models.CharField(max_length=20, choices=Relation.choices)
    alignment = models.CharField(max_length=20, choices=Alignment.choices, default=Alignment.SAME)
    confidence = models.FloatField()
    rationale = models.TextField()
    differences = models.TextField(
        help_text="Material wording, expiry, settlement, fee and liquidity differences."
    )
    left_snapshot = models.JSONField(editable=False)
    right_snapshot = models.JSONField(editable=False)
    reviewer_label = models.CharField(max_length=200)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, editable=False
    )
    reviewed_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["comparison", "version"], name="pair_review_version"),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0, confidence__lte=1),
                name="pair_confidence_range",
            ),
        ]


class EvidenceSource(models.Model):
    slug = models.SlugField(primary_key=True)
    name = models.CharField(max_length=120)
    url = models.URLField(max_length=500)
    last_checked_at = models.DateTimeField(null=True)
    last_success_at = models.DateTimeField(null=True)
    next_poll_at = models.DateTimeField(default=timezone.now)
    etag = models.CharField(max_length=500, blank=True)
    last_modified = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=200, blank=True)

    def __str__(self) -> str:
        return self.name


class EvidenceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(EvidenceSource, on_delete=models.PROTECT, related_name="items")
    external_id = models.CharField(max_length=1000)
    first_observed_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="evidence_identity")
        ]


class EvidenceRevision(AppendOnly):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(EvidenceItem, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=1000)
    excerpt = models.TextField()
    url = models.URLField(max_length=2000)
    published_at = models.DateTimeField(null=True)
    observed_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    content_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["item", "version"], name="evidence_version")]


class EvidenceLink(AppendOnly):
    class Status(models.TextChoices):
        TOPIC_ONLY = "TOPIC_ONLY", "Automatic topic association (unreviewed)"
        REVIEWED = "REVIEWED", "Reviewed relevance (not causality)"
        REJECTED = "REJECTED", "Rejected association"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(EvidenceItem, on_delete=models.PROTECT, related_name="links")
    market = models.ForeignKey(
        "markets.Market", on_delete=models.PROTECT, related_name="evidence_links"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TOPIC_ONLY)
    rationale = models.TextField()
    method = models.CharField(max_length=80, default="fed-topic-v1", editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, editable=False
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["market", "item", "created_at"])]
