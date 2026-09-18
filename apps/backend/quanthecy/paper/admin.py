from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import Account, Decision, Experiment, LedgerEntry, Opportunity, Order, Position


class ReadOnlyPaperAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


for model in (Experiment, Account, Decision, Order, Position, LedgerEntry, Opportunity):
    admin.site.register(model, ReadOnlyPaperAdmin)
