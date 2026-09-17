from django.contrib import admin

from .models import AlertEvent, AlertRule


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "watchlist", "enabled", "revision")
    list_filter = ("enabled", "kind")
    search_fields = ("name", "organization__name")
    readonly_fields = tuple(field.name for field in AlertRule._meta.fields)

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "rule", "market", "observed_at")
    readonly_fields = tuple(field.name for field in AlertEvent._meta.fields)
    list_select_related = ("organization", "rule", "market")

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
