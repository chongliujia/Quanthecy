import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from quanthecy_analytics.assistant import EXPERIMENT_VERSION as ASSISTANT_EXPERIMENT
from quanthecy_analytics.paper import VERSION
from quanthecy_analytics.paper_review import EXPERIMENT_VERSION
from redis import Redis

from quanthecy.accounts.models import User
from quanthecy.markets.models import CollectionTarget, Market
from quanthecy.markets.selection import lock_plan
from quanthecy.organizations.policies import require_org_member, require_org_role

from .models import Account, EquitySnapshot, Experiment, ExperimentMarket, LedgerEntry, Order

STRATEGIES = ("momentum", "agent_filtered", "buy_hold")
POLICY = {
    "entry_change_15m": "0.02",
    "exit_change_15m": "0",
    "holding_minutes": 60,
    "market_budget_fraction": "0.01",
    "event_budget_fraction": "0.02",
    "order_latency_seconds": 2,
    "order_expiry_seconds": 120,
    "visible_depth_fraction": "0.1",
    "slippage_bps": 10,
    "max_spread": "0.08",
    "max_quote_age_seconds": 90,
    "agent_max_age_hours": 24,
    "agent_policy": "existing_report_risk_veto",
    "outcome": "YES",
    "execution": "snapshot_ioc",
    "version": VERSION,
}


def candidates(actor: User, organization_id: UUID) -> list[dict[str, Any]]:
    require_org_member(actor, organization_id)
    now = timezone.now()
    identities = set(
        CollectionTarget.objects.filter(enabled=True, topic__enabled=True, tier="priority")
        .order_by()
        .values_list("platform", "exchange_id")
    )
    options: dict[str, list[Market]] = {"polymarket": [], "kalshi": []}
    for market in Market.objects.filter(
        status="OPEN", last_observed_at__gte=now - timedelta(seconds=180)
    ).select_related("event"):
        if (market.platform, market.exchange_id) not in identities:
            continue
        bid, ask = market.latest.get("best_bid"), market.latest.get("best_ask")
        if bid is None or ask is None or not 0 < bid <= ask < 1 or ask - bid > 0.08:
            continue
        options[market.platform].append(market)
    result = []
    for platform, rows in options.items():
        rows.sort(
            key=lambda m: (
                not m.metrics.get("quality", {}).get("price_usable", False),
                abs((m.latest["best_bid"] + m.latest["best_ask"]) / 2 - 0.5),
                str(m.id),
            )
        )
        seen: set[UUID] = set()
        for market in rows:
            if market.event_id in seen:
                continue
            seen.add(market.event_id)
            result.append(
                {
                    "id": market.id,
                    "platform": platform,
                    "title": market.title,
                    "event": market.event.title,
                    "bid": market.latest["best_bid"],
                    "ask": market.latest["best_ask"],
                }
            )
            if len(seen) == 10:
                break
    return result


@transaction.atomic
def create_experiment(
    actor: User,
    organization_id: UUID,
    ids: list[UUID],
    initial_cash: Decimal,
    name: str,
    *,
    version: str = VERSION,
    upgrade: bool = False,
    daily_review_limit: int = 10,
    assistant_version_ids: list[UUID] | None = None,
) -> Experiment:
    require_org_role(actor, organization_id, {"OWNER", "ADMIN", "MEMBER"})
    from quanthecy_analytics.assistant import AssistantGraph

    from quanthecy.agents.assistants import default_version, validate
    from quanthecy.agents.models import AssistantVersion
    from quanthecy.organizations.models import Organization

    Organization.objects.select_for_update().get(pk=organization_id)
    lock_plan()  # Serializes the globally bounded execution universe across workspaces.
    if (
        version not in {VERSION, EXPERIMENT_VERSION, ASSISTANT_EXPERIMENT}
        or not 1 <= daily_review_limit <= 20
    ):
        raise ValidationError("Unknown experiment version or invalid review limit.")
    if (
        version != ASSISTANT_EXPERIMENT
        and Experiment.objects.filter(organization_id=organization_id, version=version).exists()
    ):
        raise ValidationError("This workspace already has a paper experiment.")
    previous = (
        Experiment.objects.select_for_update()
        .filter(organization_id=organization_id)
        .order_by("-created_at", "-version", "-id")
        .first()
    )
    if previous and not upgrade and version != ASSISTANT_EXPERIMENT:
        raise ValidationError("Use the upgrade action to preserve the previous experiment.")
    if upgrade and (not previous or previous.version != VERSION or version != EXPERIMENT_VERSION):
        raise ValidationError("Only a v1 experiment can be upgraded to v2.")
    versions: list[AssistantVersion] = []
    if version == ASSISTANT_EXPERIMENT:
        selected = assistant_version_ids or []
        if len(selected) > 3 or len(set(selected)) != len(selected):
            raise ValidationError("Select up to three different published assistant versions.")
        versions = list(
            AssistantVersion.objects.filter(
                id__in=selected,
                assistant__organization_id=organization_id,
            ).select_related("assistant")
        )
        if len(versions) != len(selected):
            raise ValidationError("A selected assistant version is unavailable in this workspace.")
        default = default_version(actor, organization_id)
        versions = [default] + [v for v in versions if v.id != default.id]
        for v in versions:
            validate(AssistantGraph.model_validate(v.graph))
    if Experiment.objects.count() >= 100:
        raise ValidationError("The paper worker supports at most 100 experiments.")
    if not 1 <= len(ids) <= 20 or len(set(ids)) != len(ids):
        raise ValidationError("Select 1–20 different markets.")
    if not initial_cash.is_finite() or not Decimal(100) <= initial_cash <= Decimal(1000000):
        raise ValidationError("Virtual capital must be between 100 and 1,000,000.")
    allowed = (
        set(previous.universe.values_list("market_id", flat=True))
        if (upgrade or version == ASSISTANT_EXPERIMENT) and previous
        else {row["id"] for row in candidates(actor, organization_id)}
    )
    if not set(ids) <= allowed:
        raise ValidationError("Market selection changed. Refresh the available markets.")
    if len(set(execution_market_ids()) | set(ids)) > 20:
        raise ValidationError(
            "The shared order-book collector supports 20 markets. Pause unused experiments first."
        )
    if previous:
        previous.running = False
        previous.save(update_fields=["running", "updated_at"])
        Order.objects.filter(account__experiment=previous, status="PENDING").update(
            status="CANCELLED", reason="experiment_paused", finished_at=timezone.now()
        )
        from quanthecy.agents.models import AgentRun

        AgentRun.objects.filter(
            paper_opportunity__experiment=previous, state__in=["PENDING", "RUNNING"]
        ).update(
            state="CANCELLED",
            stage="cancelled",
            error_code="paper_paused",
            finished_at=timezone.now(),
        )
        previous.opportunities.filter(state="WAITING").update(
            state="PAUSED", reason="experiment_paused"
        )
    policy = dict(POLICY)
    if version in {EXPERIMENT_VERSION, ASSISTANT_EXPERIMENT}:
        policy.update(
            version=version,
            agent_policy="automatic_entry_review",
            daily_review_limit=daily_review_limit,
            review_validity_minutes=10,
            review_cooldown_minutes=15,
            max_review_price_drift="0.02",
            review_max_output_tokens=2048,
        )
    if version == ASSISTANT_EXPERIMENT:
        policy.update(
            agent_policy="langgraph_assistant_review",
            assistant_version_ids=[str(v.id) for v in versions],
        )
    experiment = Experiment.objects.create(
        organization_id=organization_id,
        created_by=actor,
        name=name.strip() or "Paper trading experiment",
        settings=policy,
        version=version,
    )
    markets = list(Market.objects.filter(id__in=ids))
    for market in markets:
        ExperimentMarket.objects.create(
            experiment=experiment,
            market=market,
            rules_version=market.latest["market"]["rules_version"],
        )
    now = timezone.now()
    for platform in sorted({m.platform for m in markets}):
        bindings = (
            [("momentum", None), ("buy_hold", None)] + [("assistant", v) for v in versions]
            if version == ASSISTANT_EXPERIMENT
            else [(s, None) for s in STRATEGIES]
        )
        for strategy, assistant_version in bindings:
            account = Account.objects.create(
                experiment=experiment,
                platform=platform,
                strategy=strategy,
                assistant_version=assistant_version,
                initial_cash=initial_cash,
                cash=initial_cash,
                high_water=initial_cash,
            )
            LedgerEntry.objects.create(
                account=account, kind="DEPOSIT", cash_delta=initial_cash, created_at=now
            )
            EquitySnapshot.objects.create(
                account=account,
                at=now,
                cash=initial_cash,
                equity=initial_cash,
                unrealized_pnl=0,
                realized_pnl=0,
                fees=0,
            )
    return experiment


@transaction.atomic
def set_running(
    actor: User, organization_id: UUID, running: bool, experiment_id: UUID | None = None
) -> Experiment:
    require_org_role(actor, organization_id, {"OWNER", "ADMIN", "MEMBER"})
    from quanthecy.organizations.models import Organization

    Organization.objects.select_for_update().get(pk=organization_id)
    lock_plan()
    query = Experiment.objects.select_for_update().filter(organization_id=organization_id)
    experiment = (
        get_object_or_404(query, id=experiment_id)
        if experiment_id
        else query.order_by("-created_at", "-version", "-id").first()
    )
    if experiment is None:
        from django.http import Http404

        raise Http404
    latest = query.order_by("-created_at", "-version", "-id").first()
    if running and latest is not None and experiment.id != latest.id:
        raise ValidationError("Historical experiments cannot resume after an upgrade.")
    if (
        running
        and len(
            set(execution_market_ids())
            | set(experiment.universe.values_list("market_id", flat=True))
        )
        > 20
    ):
        raise ValidationError("The shared order-book collector is at capacity.")
    experiment.running = running
    experiment.save(update_fields=["running", "updated_at"])
    if not running:
        from quanthecy.agents.models import AgentRun

        AgentRun.objects.filter(
            paper_opportunity__experiment=experiment, state__in=["PENDING", "RUNNING"]
        ).update(
            state="CANCELLED",
            stage="cancelled",
            error_code="paper_paused",
            finished_at=timezone.now(),
        )
        experiment.opportunities.filter(state="WAITING").update(
            state="PAUSED", reason="experiment_paused"
        )
        Order.objects.filter(account__experiment=experiment, status="PENDING").update(
            status="CANCELLED", reason="experiment_paused", finished_at=timezone.now()
        )
    return experiment


def execution_market_ids() -> list[UUID]:
    return list(
        ExperimentMarket.objects.filter(
            Q(experiment__running=True) | Q(experiment__accounts__positions__quantity__gt=0)
        )
        .order_by()
        .values_list("market_id", flat=True)
        .distinct()
    )


def publish_execution_universe() -> None:
    ids = execution_market_ids()
    if len(ids) > 20:
        raise ValueError("Execution collector universe exceeds capacity")
    rows = [
        {
            "market_id": str(m.id),
            "platform": m.platform,
            "exchange_id": m.exchange_id,
            "outcome_id": m.latest["outcome"]["exchange_id"],
        }
        for m in Market.objects.filter(id__in=ids).order_by("id")
    ]
    with Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5
    ) as cache:
        cache.set("paper:universe:v1", json.dumps(rows), ex=90)


@transaction.atomic
def upgrade_experiment(
    actor: User, organization_id: UUID, daily_review_limit: int = 10
) -> Experiment:
    require_org_role(actor, organization_id, {"OWNER", "ADMIN", "MEMBER"})
    from quanthecy.organizations.models import Organization

    Organization.objects.select_for_update().get(pk=organization_id)
    lock_plan()
    previous = get_object_or_404(
        Experiment.objects.select_for_update(), organization_id=organization_id, version=VERSION
    )
    initial = previous.accounts.order_by("id").first()
    if initial is None:
        raise ValidationError("The original experiment has no accounts.")
    return create_experiment(
        actor,
        organization_id,
        list(previous.universe.values_list("market_id", flat=True)),
        initial.initial_cash,
        "自动评审模拟实验 v2",
        version=EXPERIMENT_VERSION,
        upgrade=True,
        daily_review_limit=daily_review_limit,
    )
