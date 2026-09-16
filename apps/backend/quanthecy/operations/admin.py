from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html

from .console import label, tr
from .models import PlatformAuditLog, RawPayloadDeletion
from .templatetags.console import action_label

admin.site.site_header = "Quanthecy"
admin.site.site_title = label("Operations console", "运营控制台")
admin.site.index_title = label("Overview", "运行总览")
admin.site.index_template = "admin/quanthecy/index.html"


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> tuple[str, ...]:
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(PlatformAuditLog)
class PlatformAuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "operation", "actor", "subject_id", "reason")
    list_filter = ("action",)
    search_fields = ("=subject_id", "actor__email", "reason")
    list_select_related = ("actor",)
    list_per_page = 30
    search_help_text = label(
        "Search operator email, subject ID, or reason", "搜索操作人邮箱、对象 ID 或原因"
    )

    @admin.display(description=label("Action", "操作"), ordering="action")
    def operation(self, obj: PlatformAuditLog) -> str:
        return action_label(obj.action)


@admin.register(RawPayloadDeletion)
class RawPayloadDeletionAdmin(ReadOnlyAdmin):
    list_display = ("id", "job_state", "preview_count", "requested_by", "created_at", "error_code")
    list_filter = ("state",)
    list_select_related = ("requested_by",)
    list_per_page = 30
    search_fields = ("=id", "requested_by__email", "reason")
    search_help_text = label(
        "Search job ID, operator email, or reason", "搜索任务 ID、申请人邮箱或原因"
    )

    @admin.display(description=label("Status", "状态"), ordering="state")
    def job_state(self, obj: RawPayloadDeletion) -> str:
        style, en, zh = {
            "PENDING": ("neutral", "Queued", "排队中"),
            "RUNNING": ("warning", "Running", "处理中"),
            "SUCCEEDED": ("good", "Completed", "已完成"),
            "FAILED": ("bad", "Failed", "失败"),
        }[obj.state]
        return format_html('<span class="console-badge {}"><i></i>{}</span>', style, tr(en, zh))
