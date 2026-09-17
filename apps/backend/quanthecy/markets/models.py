import uuid

from django.db import models
from django.utils import translation


class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.CharField(max_length=20)
    exchange_id = models.CharField(max_length=255)
    title = models.TextField()
    observed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "exchange_id"], name="event_exchange_unique"
            )
        ]


class Market(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="markets")
    platform = models.CharField(max_length=20)
    exchange_id = models.CharField(max_length=255)
    title = models.TextField()
    status = models.CharField(max_length=20)
    first_observed_at = models.DateTimeField()
    last_observed_at = models.DateTimeField(db_index=True)
    latest = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)
    probability_change_15m = models.FloatField(null=True, db_index=True)
    volume_zscore = models.FloatField(null=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "exchange_id"], name="market_exchange_unique"
            )
        ]


class Outcome(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    market = models.ForeignKey(Market, on_delete=models.PROTECT, related_name="outcomes")
    exchange_id = models.CharField(max_length=255)
    label = models.CharField(max_length=255)
    result = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["market", "exchange_id"], name="outcome_exchange_unique"
            )
        ]


class IngestionCheckpoint(models.Model):
    collector_id = models.UUIDField(primary_key=True)
    batch_id = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class ResearchTopic(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    name_zh = models.CharField(max_length=120, blank=True)
    description = models.TextField(max_length=2000, blank=True)
    description_zh = models.TextField(max_length=2000, blank=True)
    enabled = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        default_permissions = ("add", "change", "view")

    def __str__(self) -> str:
        if (translation.get_language() or "").startswith("zh") and self.name_zh:
            return self.name_zh
        return self.name

    def clean(self) -> None:
        from .selection import validate_candidate

        validate_candidate(self)


class CollectionTarget(models.Model):
    class Tier(models.TextChoices):
        PRIORITY = "priority", "Priority"
        STANDARD = "standard", "Standard"

    class Platform(models.TextChoices):
        POLYMARKET = "polymarket", "Polymarket"
        KALSHI = "kalshi", "Kalshi"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.ForeignKey(ResearchTopic, on_delete=models.PROTECT, related_name="targets")
    platform = models.CharField(max_length=20, choices=Platform.choices)
    exchange_id = models.CharField(max_length=255)
    label = models.CharField(max_length=300)
    rationale = models.TextField(max_length=2000)
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.PRIORITY)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["platform", "exchange_id", "id"]
        default_permissions = ("add", "change", "view")
        constraints = [
            models.UniqueConstraint(
                fields=["topic", "platform", "exchange_id"], name="collection_topic_target_unique"
            )
        ]

    def __str__(self) -> str:
        return self.label

    def clean(self) -> None:
        from .selection import validate_candidate, validate_exchange_id

        validate_exchange_id(self.platform, self.exchange_id)
        validate_candidate(self)


class CollectionPlan(models.Model):
    """Singleton serialization point for operator edits and collector publication."""

    id = models.UUIDField(primary_key=True, default=uuid.UUID(int=1), editable=False)
    managed = models.BooleanField(default=False)
    controls_managed = models.BooleanField(default=False)
    polymarket_enabled = models.BooleanField(default=True)
    polymarket_interval_seconds = models.PositiveIntegerField(default=60)
    kalshi_enabled = models.BooleanField(default=True)
    kalshi_interval_seconds = models.PositiveIntegerField(default=60)
    coverage_managed = models.BooleanField(default=False)
    catalog_enabled = models.BooleanField(default=False)
    catalog_interval_seconds = models.PositiveIntegerField(default=3600)
    catalog_page_interval_seconds = models.PositiveIntegerField(default=10)
    catalog_max_pages = models.PositiveIntegerField(default=200)
    standard_interval_seconds = models.PositiveIntegerField(default=300)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ("view", "change")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(polymarket_interval_seconds__gte=15)
                & models.Q(polymarket_interval_seconds__lte=3600),
                name="polymarket_poll_interval_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(kalshi_interval_seconds__gte=15)
                & models.Q(kalshi_interval_seconds__lte=3600),
                name="kalshi_poll_interval_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    catalog_interval_seconds__gte=300, catalog_interval_seconds__lte=86400
                ),
                name="catalog_interval_seconds_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    catalog_page_interval_seconds__gte=5, catalog_page_interval_seconds__lte=300
                ),
                name="catalog_page_interval_seconds_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(catalog_max_pages__gte=1, catalog_max_pages__lte=1000),
                name="catalog_max_pages_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    standard_interval_seconds__gte=60, standard_interval_seconds__lte=3600
                ),
                name="standard_interval_seconds_bounds",
            ),
        ]


class CatalogMarket(models.Model):
    """Discovery metadata, deliberately separate from sampled prices and analytics."""

    id = models.UUIDField(primary_key=True, editable=False)
    platform = models.CharField(max_length=20)
    exchange_id = models.CharField(max_length=255)
    title = models.TextField()
    status = models.CharField(max_length=20)
    closes_at = models.DateTimeField(null=True)
    volume_24h = models.FloatField(null=True)
    volume_unit = models.CharField(max_length=20)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(db_index=True)

    class Meta:
        default_permissions = ("view",)
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "exchange_id"], name="catalog_exchange_unique"
            )
        ]
        indexes = [
            models.Index(
                fields=["platform", "status", "-volume_24h"], name="catalog_platform_activity"
            )
        ]


class CatalogCheckpoint(models.Model):
    collector_id = models.UUIDField(primary_key=True)
    page_id = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class CatalogScan(models.Model):
    platform = models.CharField(max_length=20, primary_key=True)
    observed_at = models.DateTimeField()
    scan_id = models.UUIDField()
    pages = models.PositiveIntegerField()
    rows_seen = models.PositiveIntegerField()
    accepted = models.PositiveIntegerField()
    skipped = models.PositiveIntegerField()
    state = models.CharField(max_length=20)
