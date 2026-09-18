"""Bounded review requests; scheduling is outside the portfolio transaction."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from quanthecy_analytics.intelligence import digest
from quanthecy_analytics.paper import ExecutionQuote, quote_issue
from quanthecy_analytics.paper_review import EXPERIMENT_VERSION, VERSION, EntryReview
from quanthecy_analytics.quality import VERSION as QUALITY_VERSION

from quanthecy.agents.catalog import DEFAULT_ENDPOINTS
from quanthecy.agents.configuration import (
    decrypt_key,
    endpoint,
    validate_local_limits,
    validate_model_target,
)
from quanthecy.agents.models import AgentRun, ModelConfiguration
from quanthecy.agents.services import ACTIVE, RUN_ROLES, expire_runs, runs_today
from quanthecy.organizations.models import Organization
from quanthecy.organizations.policies import require_org_role

from .models import Account, ExperimentMarket, Opportunity


def resumable(account: Account, market_id: UUID) -> Opportunity | None:
    return (
        Opportunity.objects.filter(
            experiment=account.experiment,
            market_id=market_id,
            state="WAITING",
            agent_decision__isnull=True,
            review_run__state__in=["SUCCEEDED", "FAILED", "CANCELLED"],
        )
        .select_related("review_run")
        .order_by("detected_at")
        .first()
    )


def opportunity_for(
    account: Account, target: ExperimentMarket, quote: ExecutionQuote, now: datetime
) -> Opportunity | None:
    last = (
        Opportunity.objects.filter(experiment=account.experiment, market=target.market)
        .select_related("review_run")
        .order_by("-detected_at")
        .first()
    )
    if last and last.state == "WAITING" and last.expires_at > now:
        return last
    if last and last.state == "WAITING":
        last.state, last.reason = "EXPIRED", "review_expired"
        last.save(update_fields=["state", "reason"])
    if last and now - last.detected_at < timedelta(minutes=15):
        return None
    # A baseline entry while the Agent account is already invested is not a new review candidate.
    agent = account.experiment.accounts.get(platform=account.platform, strategy="agent_filtered")
    if (
        agent.positions.filter(market=target.market, quantity__gt=0).exists()
        or agent.orders.filter(market=target.market, status="PENDING").exists()
    ):
        return None
    return Opportunity.objects.create(
        experiment=account.experiment,
        market=target.market,
        observation_id=target.market.latest["observation_id"],
        detected_at=now,
        expires_at=now + timedelta(minutes=10),
        inputs={
            "policy": account.experiment.settings,
            "observation": target.market.latest,
            "metrics": target.market.metrics,
            "probability_change_15m": target.market.probability_change_15m,
            "quote": quote.model_dump(mode="json", exclude={"raw"}),
        },
    )


def validity(
    op: Opportunity, target: ExperimentMarket, quote: ExecutionQuote | None, now: datetime
) -> str:
    if now >= op.expires_at or now < op.detected_at:
        return "review_expired"
    frozen = op.inputs["observation"]
    if (
        target.market.latest["market"]["rules_version"] != frozen["market"]["rules_version"]
        or target.market.latest["outcome"] != frozen["outcome"]
    ):
        return "rules_changed"
    issue = quote_issue(quote, now)
    if issue:
        return issue
    assert quote is not None
    original_ask = Decimal(op.inputs["quote"]["asks"][0]["price"])
    if abs(quote.asks[0].price - original_ask) > Decimal("0.02"):
        return "review_price_changed"
    return ""


def current_signal_issue(op: Opportunity, now: datetime) -> str:
    market = op.market
    if (
        market.latest["market"]["rules_version"]
        != op.inputs["observation"]["market"]["rules_version"]
    ):
        return "rules_changed"
    quality = market.metrics.get("quality", {})
    if (
        market.status != "OPEN"
        or not 0 <= (now - market.last_observed_at).total_seconds() <= 180
        or quality.get("version") != QUALITY_VERSION
        or not quality.get("price_usable")
        or market.probability_change_15m is None
        or market.probability_change_15m < 0.02
    ):
        return "review_signal_changed"
    closes = market.latest["market"].get("closes_at")
    if closes and datetime.fromisoformat(closes.replace("Z", "+00:00")) < now + timedelta(hours=1):
        return "near_market_close"
    return ""


def gate(
    op: Opportunity | None, target: ExperimentMarket, quote: ExecutionQuote, now: datetime
) -> tuple[str, str, AgentRun | None]:
    if op is None:
        return "WAIT", "review_cooldown", None
    issue = validity(op, target, quote, now)
    if issue:
        return "WAIT", issue, op.review_run
    run = op.review_run
    if run is None or run.state in ACTIVE:
        return "WAIT", op.reason, run
    if run.state != "SUCCEEDED":
        return "WAIT", "review_failed", run
    if (
        run.kind != "PAPER_REVIEW"
        or run.prompt_version != VERSION
        or run.organization_id != op.experiment.organization_id
        or run.market_id != op.market_id
        or run.cutoff != op.detected_at
        or not run.finished_at
        or run.finished_at > now
    ):
        return "WAIT", "review_invalid", run
    config = ModelConfiguration.objects.filter(organization_id=run.organization_id).first()
    if not config or not config.enabled or config.revision != run.configuration_revision:
        return "WAIT", "review_configuration_changed", run
    report = EntryReview.model_validate(run.report)
    return {
        "ALLOW": ("BUY", "review_allowed", run),
        "REJECT": ("WAIT", "review_rejected", run),
        "WAIT": ("WAIT", "review_abstained", run),
    }[report.decision]


@transaction.atomic
def schedule_one(opportunity_id: UUID) -> bool:
    original = Opportunity.objects.select_related("experiment").get(pk=opportunity_id)
    Organization.objects.select_for_update().get(pk=original.experiment.organization_id)
    # Serialize with pause/upgrade and account decisions, without making provider calls here.
    from .models import Experiment

    experiment = Experiment.objects.select_for_update().get(pk=original.experiment_id)
    op = Opportunity.objects.select_for_update().select_related("market").get(pk=opportunity_id)
    now = timezone.now()
    if not experiment.running or op.state != "WAITING" or op.expires_at <= now or op.review_run_id:
        return False
    if issue := current_signal_issue(op, now):
        op.state, op.reason = "INVALIDATED", issue
        op.save(update_fields=["state", "reason"])
        return False
    config = ModelConfiguration.objects.filter(organization_id=experiment.organization_id).first()
    reason = ""
    try:
        require_org_role(experiment.created_by, experiment.organization_id, RUN_ROLES)
        if not config or not config.enabled or not config.model:
            reason = "review_model_unavailable"
        else:
            endpoint(config.base_url, config.provider)
            validate_model_target(config.base_url, config.model)
            validate_local_limits(config)
            secret = decrypt_key(config)
            if (
                config.provider in {"openai", "anthropic"} or config.base_url in DEFAULT_ENDPOINTS
            ) and not secret:
                reason = "review_model_unavailable"
    except (ValidationError, PermissionDenied, Http404):
        reason = "review_configuration_changed"
    if not reason and config:
        expire_runs()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        paper_calls = AgentRun.objects.filter(
            organization_id=experiment.organization_id, kind="PAPER_REVIEW", created_at__gte=today
        ).count()
        if (
            paper_calls >= experiment.settings["daily_review_limit"]
            or runs_today(experiment.organization_id) >= config.daily_run_limit
        ):
            reason = "review_daily_limit"
        elif AgentRun.objects.filter(
            organization_id=experiment.organization_id, state__in=ACTIVE
        ).exists():
            reason = "review_queue_busy"
    if reason:
        if op.reason != reason:
            op.reason = reason
            op.save(update_fields=["reason"])
        return False
    assert config is not None
    op.review_run = AgentRun.objects.create(
        organization=experiment.organization,
        requested_by=experiment.created_by,
        market=op.market,
        kind="PAPER_REVIEW",
        idempotency_key=op.id,
        cutoff=op.detected_at,
        configuration_revision=config.revision,
        provider=config.provider,
        model=config.model,
        prompt_version=VERSION,
        language="zh",
    )
    op.reason = "review_pending"
    op.save(update_fields=["review_run", "reason"])
    return True


def schedule_reviews() -> None:
    now = timezone.now()
    expired = Opportunity.objects.filter(state="WAITING", expires_at__lte=now)
    AgentRun.objects.filter(paper_opportunity__in=expired, state__in=ACTIVE).update(
        state="CANCELLED", stage="cancelled", error_code="paper_review_expired", finished_at=now
    )
    expired.update(state="EXPIRED", reason="review_expired")
    ids = list(
        Opportunity.objects.filter(
            experiment__running=True,
            experiment__version=EXPERIMENT_VERSION,
            state="WAITING",
            review_run__isnull=True,
            expires_at__gt=now,
        )
        .order_by("detected_at", "id")
        .values_list("id", flat=True)[:200]
    )
    for op_id in ids:
        schedule_one(op_id)


def require_live_review(run: AgentRun) -> Opportunity:
    if run.market_id is None:
        raise PermissionDenied("Paper review requires a market")
    op = Opportunity.objects.select_related("experiment", "market").get(
        review_run=run, experiment__organization_id=run.organization_id, market_id=run.market_id
    )
    if (
        not op.experiment.running
        or op.experiment.version != EXPERIMENT_VERSION
        or op.state != "WAITING"
        or op.expires_at <= timezone.now()
        or run.prompt_version != VERSION
        or run.cutoff != op.detected_at
        or current_signal_issue(op, timezone.now())
    ):
        raise PermissionDenied("Paper review no longer active")
    return op


def review_context(run: AgentRun, context: dict[str, Any]) -> dict[str, Any]:
    op = require_live_review(run)
    result = dict(context)
    result["references"] = [
        *context["references"],
        {
            "id": "paper-entry",
            "kind": "paper_entry",
            "label": "Frozen candidate for virtual LONG YES entry",
            "value": {
                "policy": op.inputs["policy"],
                "observation_id": str(op.observation_id),
                "rules_version": op.inputs["observation"]["market"]["rules_version"],
                "probability_change_15m": op.inputs["probability_change_15m"],
                "quote": {
                    key: op.inputs["quote"][key]
                    for key in ("quote_id", "received_at", "fee_rate", "fee_model")
                },
                "best_bid": op.inputs["quote"]["bids"][0],
                "best_ask": op.inputs["quote"]["asks"][0],
            },
        },
    ]
    result["paper_review"] = {
        "version": VERSION,
        "opportunity_id": str(op.id),
        "expires_at": op.expires_at.isoformat(),
    }
    result["manifest"] = {
        **context.get("manifest", {}),
        "sha256": digest(
            {k: v for k, v in result.items() if k not in {"observations", "manifest"}}
        ),
        "reference_count": len(result["references"]),
    }
    return result
