import uuid

from django.db import models
from django.db.models.functions import Lower


class Watchlist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    name = models.CharField(max_length=80)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "organization",
                condition=models.Q(archived=False),
                name="watchlist_active_name_unique",
            )
        ]


class WatchlistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE, related_name="items")
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["watchlist", "market"], name="watchlist_market_unique")
        ]
