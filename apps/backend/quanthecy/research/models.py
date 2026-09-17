import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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
    enabled = models.BooleanField(default=True)
    poll_interval_seconds = models.PositiveIntegerField(
        default=900, validators=[MinValueValidator(300), MaxValueValidator(86400)]
    )
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_result = models.CharField(max_length=20, blank=True)
    last_entry_count = models.PositiveIntegerField(default=0)
    last_rejected_count = models.PositiveIntegerField(default=0)
    last_duplicate_count = models.PositiveIntegerField(default=0)
    last_undated_count = models.PositiveIntegerField(default=0)
    latest_published_at = models.DateTimeField(null=True, blank=True)
    poll_lease = models.UUIDField(null=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    poll_interval_seconds__gte=300, poll_interval_seconds__lte=86400
                ),
                name="evidence_poll_interval_bounds",
            )
        ]

    def __str__(self) -> str:
        return self.name


class EvidenceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(EvidenceSource, on_delete=models.PROTECT, related_name="items")
    external_id = models.CharField(max_length=1000)
    first_observed_at = models.DateTimeField(default=timezone.now, editable=False)
    document_next_poll_at = models.DateTimeField(default=timezone.now, db_index=True)
    document_last_checked_at = models.DateTimeField(null=True)
    document_last_success_at = models.DateTimeField(null=True)
    document_failures = models.PositiveIntegerField(default=0)
    document_error = models.CharField(max_length=80, blank=True)
    document_lease = models.UUIDField(null=True, editable=False)

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
    document = models.JSONField(default=dict, editable=False)
    raw_document = models.TextField(blank=True, editable=False)
    raw_feed_fields = models.JSONField(default=dict, editable=False)

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


class ResearchEvent(AppendOnly):
    """A shared research question, independent of exchange-owned events."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=160, unique=True)
    topic = models.ForeignKey("markets.ResearchTopic", on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return self.slug


class EventDefinition(AppendOnly):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(ResearchEvent, on_delete=models.PROTECT, related_name="definitions")
    version = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=240)
    title_zh = models.CharField(max_length=240, blank=True)
    scope = models.TextField(max_length=3000)
    scope_zh = models.TextField(max_length=3000, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    calendar_url = models.URLField(max_length=1000)
    source_slugs = models.JSONField(help_text="Official feed IDs eligible for candidate matching.")
    observed_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "version"], name="event_definition_version"),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="event_date_order"
            ),
        ]

    def clean(self) -> None:
        from .feed_registry import OFFICIAL_SOURCES

        if (
            not isinstance(self.source_slugs, list)
            or not 1 <= len(self.source_slugs) <= 10
            or any(not isinstance(s, str) or s not in OFFICIAL_SOURCES for s in self.source_slugs)
        ):
            raise ValidationError({"source_slugs": "Choose 1–10 registered official feed IDs."})

    def __str__(self) -> str:
        return f"{self.title} · v{self.version}"


class EventMarketLink(AppendOnly):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(ResearchEvent, on_delete=models.PROTECT, related_name="market_links")
    market = models.ForeignKey(
        "markets.Market", on_delete=models.PROTECT, related_name="research_events"
    )
    snapshot = models.JSONField(editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "market"], name="event_market_unique")
        ]


class EventEvidence(AppendOnly):
    """Automatic candidate, never an approval. Each pair of versions is independent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.ForeignKey(
        EventDefinition, on_delete=models.PROTECT, related_name="candidates"
    )
    revision = models.ForeignKey(EvidenceRevision, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["definition", "revision"], name="event_evidence_unique")
        ]

    def __str__(self) -> str:
        return f"{self.definition.title} · {self.revision.title} · v{self.revision.version}"


class EventEvidenceReview(AppendOnly):
    class Relation(models.TextChoices):
        DIRECT = "DIRECT", "Directly relevant / 直接相关"
        BACKGROUND = "BACKGROUND", "Background only / 背景资料"
        UNRELATED = "UNRELATED", "Unrelated / 不相关"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(EventEvidence, on_delete=models.PROTECT, related_name="reviews")
    relation = models.CharField(max_length=20, choices=Relation.choices)
    rationale = models.TextField(max_length=2000)
    paragraphs = models.JSONField(
        default=list,
        blank=True,
        help_text="1–5 original paragraph numbers, e.g. [2, 4]. Required for direct relevance.",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False
    )
    reviewed_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
