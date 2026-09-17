"""Audited runtime collection controls; collection scope remains independent."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from quanthecy.accounts.models import User
from quanthecy.operations.console import label, tr
from quanthecy.operations.policies import require_operator

from .models import CollectionPlan
from .selection import lock_plan, record_change, source_controls

FIELDS = (
    "polymarket_enabled",
    "polymarket_interval_seconds",
    "kalshi_enabled",
    "kalshi_interval_seconds",
)


class CollectionControlsForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    polymarket_enabled = forms.BooleanField(
        required=False, label=label("Collect Polymarket", "采集 Polymarket")
    )
    polymarket_interval_seconds = forms.IntegerField(
        min_value=15,
        max_value=3600,
        label=label("Polymarket interval · seconds", "Polymarket 采集间隔 · 秒"),
    )
    kalshi_enabled = forms.BooleanField(
        required=False, label=label("Collect Kalshi", "采集 Kalshi")
    )
    kalshi_interval_seconds = forms.IntegerField(
        min_value=15,
        max_value=3600,
        label=label("Kalshi interval · seconds", "Kalshi 采集间隔 · 秒"),
    )
    reason = forms.CharField(
        max_length=500,
        label=label("Reason for change", "修改原因"),
        widget=forms.TextInput(
            attrs={"placeholder": label("For the audit trail", "记录到操作审计")}
        ),
    )


@transaction.atomic
def configure_collection(actor: User, values: dict[str, Any]) -> CollectionPlan:
    require_operator(actor, "markets.change_collectionplan")
    form = CollectionControlsForm(values)
    if not form.is_valid():
        raise ValidationError(tr("Invalid collection settings.", "采集设置无效。"))
    data = form.cleaned_data
    plan = lock_plan()
    if plan.revision != data["revision"]:
        raise ValidationError(
            tr(
                "The plan changed. Refresh this page before saving again.",
                "采集计划已被修改，请刷新页面后重新保存。",
            )
        )
    before = {"controls_managed": plan.controls_managed, "sources": source_controls(plan)}
    for field in FIELDS:
        setattr(plan, field, data[field])
    plan.controls_managed = True
    plan.full_clean()
    plan.save(update_fields=[*FIELDS, "controls_managed"])
    record_change(
        plan,
        actor,
        plan.pk,
        data["reason"],
        {
            "kind": "runtime_controls",
            "before": before,
            "after": {"controls_managed": True, "sources": source_controls(plan)},
        },
    )
    return plan
