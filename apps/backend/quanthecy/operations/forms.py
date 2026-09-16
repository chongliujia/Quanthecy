from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from django import forms
from django.utils.dateparse import parse_datetime
from quanthecy_analytics.storage.raw import RawWindow

from .console import label


class UTCDateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self) -> None:
        super().__init__(attrs={"step": "any"})

    def format_value(self, value: Any) -> str | None:
        if isinstance(value, str):
            with suppress(ValueError):
                value = parse_datetime(value) or value
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(UTC).replace(tzinfo=None)
            return value.isoformat()
        return super().format_value(value)


class RawWindowForm(forms.Form):
    platform = forms.ChoiceField(
        label=label("Exchange", "交易所"),
        choices=[("polymarket", "Polymarket"), ("kalshi", "Kalshi")],
    )
    market_id = forms.UUIDField(
        required=False,
        label=label("Market ID", "市场 ID"),
        help_text=label("Optional · Quanthecy market UUID", "可选 · Quanthecy 市场 UUID"),
        widget=forms.TextInput(attrs={"size": 38, "style": "max-width:100%"}),
    )
    start = forms.DateTimeField(
        label=label("Start time · UTC", "开始时间 · UTC"),
        help_text=label(
            "Inclusive; select the date and time in UTC",
            "包含开始时间，请按 UTC 选择日期和时间",
        ),
        widget=UTCDateTimeInput(),
    )
    end = forms.DateTimeField(
        label=label("End time · UTC", "结束时间 · UTC"),
        help_text=label("Exclusive; maximum window: 7 days", "不包含结束时间；查询跨度最长 7 天"),
        widget=UTCDateTimeInput(),
    )

    def window(self) -> RawWindow:
        return RawWindow.model_validate(self.cleaned_data)

    def clean(self) -> dict:
        values = super().clean() or {}
        if not self.errors:
            try:
                RawWindow.model_validate(values)
            except ValueError as exc:
                raise forms.ValidationError(
                    label(
                        "Choose an increasing window of at most seven days.",
                        "结束时间须晚于开始时间，且跨度不能超过 7 天。",
                    )
                ) from exc
        return values


class DeletionConfirmationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, max_length=30000)
    reason = forms.CharField(
        label=label("Reason for cleanup", "清理原因"),
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label=label(
            "I confirm clearing the eligible exchange JSON in this preview.",
            "我确认清理本次预览范围内可清除的交易所 JSON。",
        )
    )
