import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AlertRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    watchlist = models.ForeignKey(
        "watchlists.Watchlist", on_delete=models.PROTECT, related_name="alert_rules"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=30,
        choices=[("PROBABILITY_MOVE", "Probability move"), ("SPREAD_WIDENING", "Spread widening")],
    )
    direction = models.CharField(
        max_length=10,
        choices=[("EITHER", "Either"), ("UP", "Up"), ("DOWN", "Down")],
        default="EITHER",
    )
    threshold_pp = models.DecimalField(max_digits=5, decimal_places=2)
    window_minutes = models.PositiveIntegerField(default=15)
    cooldown_minutes = models.PositiveIntegerField(default=30)
    enabled = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    effective_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(threshold_pp__gt=0, threshold_pp__lte=100),
                name="alert_threshold_range",
            ),
            models.CheckConstraint(
                condition=models.Q(window_minutes__in=[5, 15, 60]), name="alert_window_range"
            ),
            models.CheckConstraint(
                condition=models.Q(cooldown_minutes__gte=1, cooldown_minutes__lte=1440),
                name="alert_cooldown_range",
            ),
        ]


class AlertCursor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="cursors")
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    last_observed_at = models.DateTimeField(null=True)
    last_observation_id = models.UUIDField(null=True)
    evaluated_at = models.DateTimeField(null=True)
    armed = models.BooleanField(default=True)
    last_triggered_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=30, default="WAITING")
    reason = models.CharField(max_length=80, blank=True)
    value_pp = models.FloatField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rule", "market"], name="alert_cursor_unique")
        ]


class AlertEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    rule = models.ForeignKey(AlertRule, on_delete=models.PROTECT)
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    observation_id = models.UUIDField()
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    snapshot = models.JSONField()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "-created_at"], name="alert_org_time_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "market", "revision", "observation_id"], name="alert_event_dedup"
            )
        ]


class AlertReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="alert_read_unique")]
