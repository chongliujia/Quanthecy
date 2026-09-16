from typing import Any

from django import forms
from django.contrib import admin
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import HttpRequest

from quanthecy.api.auth import current_user
from quanthecy.operations.console import label

from .models import CollectionTarget, Event, IngestionCheckpoint, Market, Outcome, ResearchTopic
from .selection import lock_plan, record_change


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


# Operator changes are serialized with publication so a plan cannot exceed its bounds
# through simultaneous edits. Disabling a target leaves all observations intact.


class SelectionForm(forms.ModelForm):
    change_reason = forms.CharField(
        label=label("Reason for change", "修改原因"),
        max_length=500,
        help_text=label("Recorded in the audit trail.", "将记录到操作审计。"),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        labels = {
            "slug": ("Stable topic identifier", "主题标识"),
            "name": ("English name", "英文名称"),
            "name_zh": ("Chinese name", "中文名称"),
            "description": ("English description", "英文说明"),
            "description_zh": ("Chinese description", "中文说明"),
            "enabled": ("Collection enabled", "启用采集"),
            "is_public": ("Show in the market explorer", "在用户市场页展示主题"),
            "topic": ("Research topic", "研究主题"),
            "platform": ("Exchange", "交易所"),
            "exchange_id": ("Exchange market ID / ticker", "交易所市场 ID / 合约代码"),
            "label": ("Market label", "市场名称"),
            "rationale": ("Selection rationale", "纳入理由"),
        }
        for name, pair in labels.items():
            if name in self.fields:
                self.fields[name].label = label(*pair)
        if "enabled" in self.fields:
            self.fields["enabled"].help_text = label(
                "Pausing stops collection for this membership. Other topics may still collect "
                "the same market. History is retained.",
                "暂停后停止此主题下的采集；若其他主题仍启用同一市场，采集会继续。历史数据保留。",
            )


class SelectionAdmin(admin.ModelAdmin):
    form = SelectionForm
    readonly_fields = ("id", "updated_at")
    actions = None

    @transaction.atomic
    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> Any:
        if request.method == "POST":
            lock_plan()
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        plan = lock_plan()
        before = model_to_dict(type(obj).objects.get(pk=obj.pk)) if change else None
        obj.full_clean()
        super().save_model(request, obj, form, change)
        # Values are identifiers, labels and policy fields, with no credentials.
        import json

        from django.core.serializers.json import DjangoJSONEncoder

        details = json.loads(
            json.dumps(
                {"model": obj._meta.label_lower, "before": before, "after": model_to_dict(obj)},
                cls=DjangoJSONEncoder,
            )
        )
        record_change(
            plan, current_user(request), obj.pk, form.cleaned_data["change_reason"], details
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(ResearchTopic)
class ResearchTopicAdmin(SelectionAdmin):
    list_display = ("name", "name_zh", "slug", "enabled", "is_public", "updated_at")
    list_filter = ("enabled", "is_public")
    search_fields = ("name", "name_zh", "slug")


@admin.register(CollectionTarget)
class CollectionTargetAdmin(SelectionAdmin):
    list_display = ("label", "topic", "platform", "exchange_id", "enabled", "updated_at")
    list_filter = ("topic", "platform", "enabled")
    search_fields = ("label", "exchange_id")
    list_select_related = ("topic",)
