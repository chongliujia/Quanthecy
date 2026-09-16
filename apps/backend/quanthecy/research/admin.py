from typing import Any

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import ModelForm
from django.http import HttpRequest

from quanthecy.api.auth import current_user
from quanthecy.markets.models import Market
from quanthecy.operations.console import label, tr

from .models import (
    Comparison,
    ComparisonReview,
    EvidenceItem,
    EvidenceLink,
    EvidenceRevision,
    EvidenceSource,
)
from .reviews import append_review, snapshot


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


@admin.register(EvidenceSource)
class EvidenceSourceAdmin(HistoricalAdmin):
    list_display = ("name", "last_success_at", "last_checked_at", "error")

    def has_add_permission(self, request: HttpRequest) -> bool:
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
    readonly_fields = ("document", "raw_document")

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
