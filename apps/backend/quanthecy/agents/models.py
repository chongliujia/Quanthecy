import uuid

from django.conf import settings
from django.db import models


class ModelConfiguration(models.Model):
    organization = models.OneToOneField(
        "organizations.Organization", primary_key=True, on_delete=models.PROTECT
    )
    provider = models.CharField(max_length=30, default="openai_compatible")
    base_url = models.URLField(max_length=500, default="https://api.openai.com/v1")
    model = models.CharField(max_length=160, blank=True)
    encrypted_api_key = models.TextField(blank=True)
    enabled = models.BooleanField(default=False)
    daily_run_limit = models.PositiveIntegerField(default=10)
    max_output_tokens = models.PositiveIntegerField(default=2000)
    revision = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)


class AgentRun(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "Queued"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    market = models.ForeignKey("markets.Market", null=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, default="RESEARCH")
    idempotency_key = models.UUIDField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    stage = models.CharField(max_length=30, default="queued")
    cutoff = models.DateTimeField()
    configuration_revision = models.PositiveIntegerField()
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=160)
    prompt_version = models.CharField(max_length=40, default="research-v1")
    workflow = models.CharField(max_length=20, default="single")
    language = models.CharField(max_length=2, default="en")
    reserved_calls = models.PositiveSmallIntegerField(default=1)
    steps = models.JSONField(default=list)
    context = models.JSONField(default=dict)
    report = models.JSONField(null=True)
    usage = models.JSONField(default=dict)
    error_code = models.CharField(max_length=80, blank=True)
    validation_errors = models.JSONField(default=list)
    lease_token = models.UUIDField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "market", "-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"], name="agent_request_unique"
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(state__in=["PENDING", "RUNNING"]),
                name="agent_one_active_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
                ),
                name="agent_valid_state",
            ),
        ]
