from django.contrib import admin

from .models import Watchlist, WatchlistItem


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "archived", "created_at")
    list_filter = ("archived",)
    search_fields = ("name", "organization__name")
    readonly_fields = ("id", "organization", "name", "archived", "created_at")

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ("watchlist", "market", "position", "added_at")
    readonly_fields = ("id", "watchlist", "market", "position", "added_at")

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
