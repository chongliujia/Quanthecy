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
    class Platform(models.TextChoices):
        POLYMARKET = "polymarket", "Polymarket"
        KALSHI = "kalshi", "Kalshi"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.ForeignKey(ResearchTopic, on_delete=models.PROTECT, related_name="targets")
    platform = models.CharField(max_length=20, choices=Platform.choices)
    exchange_id = models.CharField(max_length=255)
    label = models.CharField(max_length=300)
    rationale = models.TextField(max_length=2000)
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
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ("view",)
