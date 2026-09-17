from typing import Any

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import ModelForm
from django.http import HttpRequest

from quanthecy.api.auth import current_user
from quanthecy.markets.models import Market
from quanthecy.operations.console import label, tr

from .feed_registry import FEEDS
from .models import (
    Comparison,
    ComparisonReview,
    EvidenceItem,
    EvidenceLink,
    EvidenceRevision,
    EvidenceSource,
)
from .reviews import append_review, snapshot
from .source_controls import configure_source


class HistoricalAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Comparison)
class ComparisonAdmin(HistoricalAdmin):
    list_display = ("slug", "left", "right", "created_at")
    autocomplete_fields = ("left", "right")


class ReviewForm(ModelForm):
    class Meta:
        model = ComparisonReview
        fields = "__all__"

    def clean(self) -> dict[str, Any]:
        values = super().clean() or {}
        pair = values.get("comparison")
        if pair:
            if pair.left.platform == pair.right.platform:
                raise ValidationError("Choose markets on different platforms.")
            snapshot(pair.left)
            snapshot(pair.right)
        return values


@admin.register(ComparisonReview)
class ComparisonReviewAdmin(HistoricalAdmin):
    form = ReviewForm
    list_display = ("title", "version", "relation", "reviewer_label", "reviewed_at")
    list_filter = ("relation", "topic")
    readonly_fields = ("version", "reviewed_at", "reviewed_by", "left_snapshot", "right_snapshot")

    def save_model(
        self, request: HttpRequest, obj: ComparisonReview, form: Any, change: bool
    ) -> None:
        obj.reviewed_by = current_user(request)
        append_review(obj)


class SourceForm(ModelForm):
    change_reason = forms.CharField(label=label("Reason for change", "修改原因"), max_length=500)

    class Meta:
        model = EvidenceSource
        fields = ("enabled", "poll_interval_seconds")
        labels = {
            "enabled": label("Collection enabled", "启用采集"),
            "poll_interval_seconds": label("Polling interval (seconds)", "采集间隔（秒）"),
        }
        help_texts = {
            "enabled": label("Pausing preserves collected history.", "暂停后保留已采集历史。"),
            "poll_interval_seconds": label(
                "300–86400 seconds; failures back off automatically.",
                "300–86400 秒，失败后自动延长重试间隔。",
            ),
        }


@admin.register(EvidenceSource)
class EvidenceSourceAdmin(admin.ModelAdmin):
    form = SourceForm
    list_display = (
        "name",
        "source_kind",
        "enabled",
        "collection_state",
        "poll_interval_seconds",
        "last_success_at",
        "next_poll_at",
        "last_entry_count",
        "error",
    )
    list_filter = ("enabled", "last_result")
    search_fields = ("name", "slug")
    actions = None
    readonly_fields = (
        "slug",
        "name",
        "url",
        "source_kind",
        "source_notes",
        "collection_state",
        "last_checked_at",
        "last_success_at",
        "next_poll_at",
        "latest_published_at",
        "last_entry_count",
        "last_rejected_count",
        "last_duplicate_count",
        "last_undated_count",
        "consecutive_failures",
        "error",
    )

    @admin.display(description=label("Source type", "来源类型"))
    def source_kind(self, obj: EvidenceSource) -> str:
        spec = FEEDS.get(obj.slug)
        return tr("Official", "官方") if spec and spec.kind == "OFFICIAL" else tr("Media", "媒体")

    @admin.display(description=label("Collection status", "采集状态"))
    def collection_state(self, obj: EvidenceSource) -> str:
        from .services import source_value

        names = {
            "paused": ("Paused", "已暂停"),
            "pending": ("Pending", "等待采集"),
            "healthy": ("Healthy", "采集正常"),
            "partial": ("Partial", "部分条目存在问题"),
            "empty": ("Empty feed", "无可用条目"),
            "retrying": ("Retrying", "等待重试"),
            "stale": ("Overdue", "采集超时未更新"),
        }
        return tr(*names[source_value(obj).status])

    @admin.display(description=label("Source notes", "来源说明"))
    def source_notes(self, obj: EvidenceSource) -> str:
        spec = FEEDS.get(obj.slug)
        if spec and spec.notes:
            return tr(spec.notes, "首次连通性检查返回 HTTP 403，请确认部署环境可访问后再启用。")
        return tr(
            "Feed metadata and excerpts. Full-page capture is separately allowlisted.",
            "采集订阅元数据与摘要。正文采集使用单独白名单。",
        )

    def save_model(
        self, request: HttpRequest, obj: EvidenceSource, form: Any, change: bool
    ) -> None:
        configure_source(
            obj.pk,
            enabled=obj.enabled,
            interval=obj.poll_interval_seconds,
            reason=form.cleaned_data["change_reason"],
            actor=current_user(request),
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(EvidenceItem)
class EvidenceItemAdmin(HistoricalAdmin):
    list_display = (
        "id",
        "source",
        "first_observed_at",
        "document_checked",
        "document_status",
    )
    search_fields = ("external_id",)
    list_filter = ("source", "document_error")

    @admin.display(
        description=label("Document captured", "正文获取时间"), ordering="document_last_success_at"
    )
    def document_checked(self, obj: EvidenceItem) -> Any:
        return obj.document_last_success_at

    @admin.display(description=label("Document status", "正文采集状态"))
    def document_status(self, obj: EvidenceItem) -> str:
        from .documents import PATHS

        if obj.source_id not in PATHS:
            return tr("Feed excerpt only", "仅采集订阅摘要")
        if obj.document_error:
            return tr("Retrying", "等待重试") + f" · {obj.document_error}"
        return (
            tr("Captured", "已采集") if obj.document_last_success_at else tr("Pending", "等待采集")
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(EvidenceRevision)
class EvidenceRevisionAdmin(HistoricalAdmin):
    list_display = ("title", "version", "published_at", "observed_at", "has_document")
    search_fields = ("title",)
    readonly_fields = ("document", "raw_document", "raw_feed_fields")

    @admin.display(description=label("Official text", "官方正文"), boolean=True)
    def has_document(self, obj: EvidenceRevision) -> bool:
        return bool(obj.document)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(EvidenceLink)
class EvidenceLinkAdmin(HistoricalAdmin):
    list_display = ("item", "market", "status", "created_at")
    list_filter = ("status",)
    autocomplete_fields = ("item", "market")
    readonly_fields = ("created_at", "method", "reviewed_by")

    @transaction.atomic
    def save_model(self, request: HttpRequest, obj: EvidenceLink, form: Any, change: bool) -> None:
        Market.objects.select_for_update().get(pk=obj.market_id)
        obj.reviewed_by = current_user(request)
        obj.method = "operator-review-v1"
        obj.save()


# Register the event review surfaces after the shared historical admin base.
from . import event_admin  # noqa: E402, F401
