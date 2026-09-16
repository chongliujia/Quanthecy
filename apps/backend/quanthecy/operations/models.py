import uuid

from django.conf import settings
from django.db import models


class PlatformAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    subject_id = models.UUIDField()
    reason = models.CharField(max_length=500)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        default_permissions = ("view",)
        permissions = [("view_collection_status", "Can view platform collection status")]


class RawPayloadDeletion(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    scope = models.JSONField()
    preview_count = models.PositiveIntegerField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        default_permissions = ("view",)
        permissions = [
            ("view_raw_payloads", "Can inspect raw exchange payloads"),
            ("purge_raw_payloads", "Can request raw exchange payload deletion"),
        ]
        indexes = [models.Index(fields=["state", "created_at"])]
