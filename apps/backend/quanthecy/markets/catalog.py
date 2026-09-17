"""Directory reconciliation and operator selection. Discovery never creates price history."""

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from ninja import Schema
from pydantic import AwareDatetime, ConfigDict, Field, model_validator
from quanthecy_analytics.storage.clickhouse import ClickHouseRepository

from quanthecy.accounts.models import User
from quanthecy.operations.console import label, tr
from quanthecy.operations.policies import require_operator

from .models import (
    CatalogCheckpoint,
    CatalogMarket,
    CatalogScan,
    CollectionPlan,
    CollectionTarget,
    Market,
    ResearchTopic,
)
from .selection import lock_plan, market_id, record_change, validate_candidate, validate_exchange_id


class CatalogItem(Schema):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    exchange_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=10000)
    status: Literal["OPEN", "CLOSED", "RESOLVED", "UNKNOWN"]
    closes_at: AwareDatetime | None
    volume_24h: float | None = Field(ge=0, allow_inf_nan=False)
    volume_unit: Literal["USD", "CONTRACTS"]


class CatalogPageInput(Schema):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    page_id: int = Field(ge=1)
    platform: Literal["polymarket", "kalshi"]
    observed_at: AwareDatetime
    scan_id: UUID
    pages: int = Field(ge=1, le=1000)
    rows_seen: int = Field(ge=0, le=100000)
    accepted: int = Field(ge=0, le=100000)
    skipped: int = Field(ge=0, le=100000)
    state: Literal["scanning", "complete", "capped"]
    items: list[CatalogItem] = Field(max_length=100)

    @model_validator(mode="after")
    def consistent(self) -> "CatalogPageInput":
        if self.accepted + self.skipped != self.rows_seen or self.accepted < len(self.items):
            raise ValueError("Invalid catalog counters")
        ids = set()
        for item in self.items:
            validate_exchange_id(self.platform, item.exchange_id)
            if item.id != market_id(self.platform, item.exchange_id) or item.id in ids:
                raise ValueError("Invalid or duplicate catalog identity")
            if item.volume_unit != ("USD" if self.platform == "polymarket" else "CONTRACTS"):
                raise ValueError("Invalid catalog volume unit")
            ids.add(item.id)
        return self


@transaction.atomic
def reconcile_page(collector: UUID, value: dict[str, Any]) -> bool:
    page = CatalogPageInput.model_validate(value)
    CatalogCheckpoint.objects.get_or_create(collector_id=collector)
    checkpoint = CatalogCheckpoint.objects.select_for_update().get(collector_id=collector)
    if page.page_id <= checkpoint.page_id:
        return False
    if page.page_id != checkpoint.page_id + 1:
        raise ValueError("Missing catalog page; checkpoint retained")
    for item in page.items:
        values = item.model_dump(exclude={"id"})
        values.update(platform=page.platform, last_seen_at=page.observed_at)
        row, created = CatalogMarket.objects.get_or_create(
            id=item.id,
            defaults={
                **values,
                "first_seen_at": page.observed_at,
            },
        )
        if not created:
            # Conditional updates also protect against delayed independent collectors.
            CatalogMarket.objects.filter(pk=row.pk, last_seen_at__lte=page.observed_at).update(
                **values
            )
            CatalogMarket.objects.filter(pk=row.pk, first_seen_at__gt=page.observed_at).update(
                first_seen_at=page.observed_at
            )
    scan_values = page.model_dump(exclude={"schema_version", "page_id", "items", "platform"})
    scan, created = CatalogScan.objects.get_or_create(platform=page.platform, defaults=scan_values)
    if not created:
        CatalogScan.objects.filter(pk=scan.pk, observed_at__lte=page.observed_at).update(
            **scan_values
        )
    checkpoint.page_id = page.page_id
    checkpoint.save(update_fields=["page_id", "updated_at"])
    return True


def run_catalog_ingestion(repository: ClickHouseRepository) -> int:
    total = 0
    for collector in repository.catalog_collectors():
        checkpoint = CatalogCheckpoint.objects.filter(collector_id=collector).first()
        for page in repository.catalog_pages(collector, checkpoint.page_id if checkpoint else 0):
            total += reconcile_page(collector, page)
    return total


COVERAGE_FIELDS = (
    "catalog_enabled",
    "catalog_interval_seconds",
    "catalog_page_interval_seconds",
    "catalog_max_pages",
    "standard_interval_seconds",
)


class CoverageControlsForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    catalog_enabled = forms.BooleanField(
        required=False, label=label("Discover market directory", "自动发现市场目录")
    )
    catalog_interval_seconds = forms.IntegerField(
        min_value=300,
        max_value=86400,
        label=label("Pause between scans · seconds", "轮次之间的间隔 · 秒"),
    )
    catalog_page_interval_seconds = forms.IntegerField(
        min_value=5,
        max_value=300,
        label=label("Minimum page interval · seconds", "分页请求间隔 · 秒"),
    )
    catalog_max_pages = forms.IntegerField(
        min_value=1,
        max_value=1000,
        label=label("Maximum pages per scan / exchange", "每轮每交易所最多页数"),
    )
    standard_interval_seconds = forms.IntegerField(
        min_value=60,
        max_value=3600,
        label=label("Standard tier interval · seconds", "普通层采集间隔 · 秒"),
    )
    reason = forms.CharField(max_length=500, label=label("Reason for change", "修改原因"))


@transaction.atomic
def configure_coverage(actor: User, values: dict[str, Any]) -> CollectionPlan:
    require_operator(actor, "markets.change_collectionplan")
    form = CoverageControlsForm(values)
    if not form.is_valid():
        raise ValidationError(tr("Invalid discovery settings.", "目录采集设置无效。"))
    data = form.cleaned_data
    plan = lock_plan()
    if plan.revision != data["revision"]:
        raise ValidationError(
            tr("The plan changed. Refresh before saving.", "计划已改变，请刷新后保存。")
        )
    before = {field: getattr(plan, field) for field in COVERAGE_FIELDS}
    for field in COVERAGE_FIELDS:
        setattr(plan, field, data[field])
    plan.coverage_managed = True
    plan.controls_managed = True
    plan.full_clean()
    plan.save(update_fields=[*COVERAGE_FIELDS, "coverage_managed", "controls_managed"])
    record_change(
        plan,
        actor,
        plan.pk,
        data["reason"],
        {
            "kind": "directory_controls",
            "before": before,
            "after": {field: getattr(plan, field) for field in COVERAGE_FIELDS},
        },
    )
    return plan


@transaction.atomic
def select_catalog(
    actor: User, *, ids: list[UUID], topic_id: UUID, tier: str, revision: int, reason: str
) -> int:
    require_operator(actor, "markets.add_collectiontarget")
    require_operator(actor, "markets.change_collectiontarget")
    require_operator(actor, "markets.change_collectionplan")
    if (
        not ids
        or len(ids) > 50
        or len(set(ids)) != len(ids)
        or tier not in ("priority", "standard")
        or not reason.strip()
        or len(reason) > 500
    ):
        raise ValidationError(
            tr("Select 1–50 markets and provide a reason.", "请选择 1–50 个市场并填写原因。")
        )
    plan = lock_plan()
    if not plan.managed:
        raise ValidationError(
            tr(
                "Activate a managed collection plan before adding directory markets.",
                "请先启用托管采集名单，再加入目录市场。",
            )
        )
    if plan.revision != revision:
        raise ValidationError(
            tr("The plan changed. Refresh before saving.", "计划已改变，请刷新后保存。")
        )
    topic = ResearchTopic.objects.filter(pk=topic_id, enabled=True).first()
    if topic is None:
        raise ValidationError(tr("Select an enabled research topic.", "请选择已启用的研究主题。"))
    rows = list(
        CatalogMarket.objects.filter(
            id__in=ids, status="OPEN", last_seen_at__gte=timezone.now() - timedelta(hours=24)
        )
    )
    if len(rows) != len(ids):
        raise ValidationError(
            tr(
                "Some markets are closed, stale or unavailable. Refresh the directory.",
                "部分市场已关闭、过期或不存在，请刷新目录。",
            )
        )
    sampled = {row.pk: row for row in Market.objects.filter(pk__in=ids)}
    changes = []
    for row in rows:
        observed = sampled.get(row.pk)
        if observed and observed.last_observed_at >= row.last_seen_at and observed.status != "OPEN":
            raise ValidationError(
                tr("A selected market has closed since discovery.", "所选市场在发现后已关闭。")
            )
        previous = (
            CollectionTarget.objects.filter(
                topic=topic, platform=row.platform, exchange_id=row.exchange_id
            )
            .values("enabled", "tier")
            .first()
        )
        target, _ = CollectionTarget.objects.update_or_create(
            topic=topic,
            platform=row.platform,
            exchange_id=row.exchange_id,
            defaults={
                "label": row.title[:300],
                "rationale": reason,
                "enabled": True,
                "tier": tier,
            },
        )
        changes.append(
            {"target": str(target.pk), "before": previous, "after": {"enabled": True, "tier": tier}}
        )
    validate_candidate()  # Atomic rollback if the aggregate plan exceeds its capacity.
    plan.coverage_managed = True
    plan.controls_managed = True
    plan.save(update_fields=["coverage_managed", "controls_managed"])
    record_change(plan, actor, topic.pk, reason, {"kind": "catalog_selection", "changes": changes})
    return len(rows)


class CatalogMarketOut(Schema):
    id: UUID
    platform: str
    exchange_id: str
    title: str
    status: str
    closes_at: datetime | None
    volume_24h: float | None
    volume_unit: str
    last_seen_at: datetime
    stale: bool
    collection: str
    has_history: bool


class CatalogPage(Schema):
    items: list[CatalogMarketOut]
    total: int
    offset: int
    limit: int


def directory(
    *,
    platform: str = "",
    search: str = "",
    offset: int = 0,
    limit: int = 20,
    collected: str = "all",
) -> CatalogPage:
    query = CatalogMarket.objects.all()
    if platform:
        query = query.filter(platform=platform)
    if search:
        query = query.filter(Q(title__icontains=search) | Q(exchange_id__icontains=search))
    if collected != "all":
        history = Market.objects.values("id")
        query = (
            query.filter(pk__in=history)
            if collected == "collected"
            else query.exclude(pk__in=history)
        )
    total = query.count()
    # Volumes have different units. Rank activity only within an explicitly selected exchange.
    rows = list(
        query.order_by(
            *([F("volume_24h").desc(nulls_last=True)] if platform else []), "-last_seen_at", "id"
        )[offset : offset + limit]
    )
    observed = {row.pk: row for row in Market.objects.filter(pk__in=[row.pk for row in rows])}
    targets: dict[UUID, str] = {}
    for target in CollectionTarget.objects.filter(enabled=True, topic__enabled=True):
        identity = market_id(target.platform, target.exchange_id)
        if targets.get(identity) != "priority":
            targets[identity] = target.tier
    items = []
    for row in rows:
        market = observed.get(row.pk)
        status = (
            market.status if market and market.last_observed_at >= row.last_seen_at else row.status
        )
        items.append(
            CatalogMarketOut(
                id=row.pk,
                platform=row.platform,
                exchange_id=row.exchange_id,
                title=row.title,
                status=status,
                closes_at=row.closes_at,
                volume_24h=row.volume_24h,
                volume_unit=row.volume_unit,
                last_seen_at=row.last_seen_at,
                stale=row.last_seen_at < timezone.now() - timedelta(hours=24),
                collection=targets.get(row.pk, "history" if market else "directory"),
                has_history=bool(market),
            )
        )
    return CatalogPage(items=items, total=total, offset=offset, limit=limit)


def discovery_health() -> list[dict[str, Any]]:
    """Runtime liveness is distinct from persisted scan progress."""
    import json

    from django.conf import settings
    from redis import Redis

    plan = CollectionPlan.objects.first()
    readings: list[Any] = [None, None]
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
        ) as cache:
            readings = cache.mget(["collector:catalog:polymarket", "collector:catalog:kalshi"])
    except Exception:
        pass
    result = []
    for platform, raw in zip(("polymarket", "kalshi"), readings, strict=True):
        state = "offline"
        if plan and (not plan.catalog_enabled or not getattr(plan, f"{platform}_enabled")):
            state = "paused"
        else:
            try:
                if not isinstance(raw, (str, bytes)) or len(raw) > 4096:
                    raise ValueError
                record = json.loads(raw)
                if not isinstance(record, dict):
                    raise ValueError
                at = datetime.fromisoformat(record["checked_at"])
                if at.tzinfo is not None and 0 <= (timezone.now() - at).total_seconds() <= 180:
                    state = (
                        "pending"
                        if not plan or record.get("revision") != plan.revision
                        else "error"
                        if record.get("error")
                        else "online"
                    )
            except (ValueError, TypeError, KeyError):
                pass
        result.append({"platform": platform, "state": state})
    return result
