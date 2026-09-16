import uuid

from django.db import models


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
