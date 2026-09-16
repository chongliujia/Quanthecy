from django.contrib import admin
from django.http import HttpRequest

from .models import Organization, OrganizationMembership


class WorkspaceReadOnlyAdmin(admin.ModelAdmin):
    """Membership writes must go through transactional services."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(Organization)
class OrganizationAdmin(WorkspaceReadOnlyAdmin):
    list_display = ("name", "kind", "id", "created_at")
    search_fields = ("name", "slug")


@admin.register(OrganizationMembership)
class MembershipAdmin(WorkspaceReadOnlyAdmin):
    list_display = ("organization", "user", "role", "created_at")
    list_filter = ("role",)
    list_select_related = ("organization", "user")
