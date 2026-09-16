from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import Event, IngestionCheckpoint, Market, Outcome


class ReadOnlyMarketAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Market)
class MarketAdmin(ReadOnlyMarketAdmin):
    list_display = ("title", "platform", "status", "first_observed_at", "last_observed_at")
    list_filter = ("platform", "status")
    search_fields = ("title", "exchange_id")


admin.site.register([Event, Outcome, IngestionCheckpoint], ReadOnlyMarketAdmin)
