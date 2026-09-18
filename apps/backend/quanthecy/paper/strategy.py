from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum
from quanthecy_analytics.paper import ZERO, ExecutionQuote, money, quote_issue
from quanthecy_analytics.paper_review import EXPERIMENT_VERSION
from quanthecy_analytics.quality import VERSION as QUALITY_VERSION

from quanthecy.agents.models import AgentRun

from . import reviews
from .models import Account, Decision, ExperimentMarket, Order, Position


def decide(
    account: Account, target: ExperimentMarket, quote: ExecutionQuote | None, now: datetime
) -> None:
    market = target.market
    automatic = account.experiment.version == EXPERIMENT_VERSION
    opportunity = (
        reviews.resumable(account, market.id)
        if automatic and account.strategy == "agent_filtered"
        else None
    )
    phase = "REVIEW" if opportunity else "SIGNAL"
    observation_id = market.latest.get("observation_id")
    if (
        not observation_id
        or account.decisions.filter(
            market=market, observation_id=observation_id, phase=phase
        ).exists()
    ):
        return
    if (
        phase == "SIGNAL"
        and account.decisions.filter(
            market=market, created_at__gt=now - timedelta(minutes=5)
        ).exists()
    ):
        return
    if account.orders.filter(market=market, status="PENDING").exists():
        return
    position = Position.objects.filter(account=account, market=market).first()
    held = position is not None and position.quantity > 0
    action, reason = "WAIT", quote_issue(quote, now)
    agent_run = opportunity.review_run if opportunity else None
    change = market.probability_change_15m
    quality = market.metrics.get("quality", {})
    if not reason and market.latest.get("market", {}).get("rules_version") != target.rules_version:
        reason = "rules_changed"
    if not reason and (
        market.status != "OPEN" or not 0 <= (now - market.last_observed_at).total_seconds() <= 180
    ):
        reason = "stale_market_observation"
    if not reason and held:
        if account.strategy == "buy_hold":
            reason = "hold_until_resolution"
        elif position is not None and now - position.opened_at >= timedelta(minutes=60):
            action, reason = "SELL", "holding_period_elapsed"
        elif (
            change is not None
            and quality.get("version") == QUALITY_VERSION
            and quality.get("price_usable")
            and change <= 0
        ):
            action, reason = "SELL", "momentum_reversed"
        else:
            reason = "holding_position"
    elif not reason:
        closes_at = market.latest.get("market", {}).get("closes_at")
        if closes_at and datetime.fromisoformat(closes_at.replace("Z", "+00:00")) < now + timedelta(
            hours=1
        ):
            reason = "near_market_close"
        elif (
            position
            and position.closed_at
            and (account.strategy == "buy_hold" or now - position.closed_at < timedelta(minutes=15))
        ):
            reason = "reentry_cooldown"
        elif account.strategy == "buy_hold":
            action, reason = "BUY", "buy_hold_benchmark"
        elif (
            quality.get("version") != QUALITY_VERSION
            or not quality.get("price_usable")
            or change is None
        ):
            reason = "insufficient_price_history"
        elif change < 0.02:
            reason = "momentum_below_threshold"
        else:
            action, reason = "BUY", "positive_15m_momentum"
            if account.strategy == "agent_filtered" and not automatic:
                agent_run = (
                    AgentRun.objects.filter(
                        organization=account.experiment.organization,
                        market=market,
                        kind="RESEARCH",
                        state="SUCCEEDED",
                        finished_at__lte=now,
                        finished_at__gte=now - timedelta(hours=24),
                        cutoff__lte=now,
                        cutoff__gte=now - timedelta(hours=24),
                    )
                    .order_by("-finished_at", "-id")
                    .first()
                )
                report = agent_run.report if agent_run else None
                if not isinstance(report, dict):
                    action, reason = "WAIT", "awaiting_agent_report"
                elif (
                    report.get("action") not in {"WATCH", "INVESTIGATE"}
                    or report.get("risk_flags") != []
                ):
                    action, reason = "WAIT", "agent_risk_veto"
    quantity, budget, limit_price = ZERO, ZERO, ZERO
    if action == "BUY" and quote:
        reserved = (
            account.orders.filter(status="PENDING", side="BUY").aggregate(total=Sum("budget"))[
                "total"
            ]
            or ZERO
        )
        event_cost = (
            account.positions.filter(market__event_id=market.event_id, quantity__gt=0).aggregate(
                total=Sum("cost_basis")
            )["total"]
            or ZERO
        )
        event_reserved = (
            account.orders.filter(
                status="PENDING", side="BUY", market__event_id=market.event_id
            ).aggregate(total=Sum("budget"))["total"]
            or ZERO
        )
        budget = money(
            min(
                account.cash - reserved,
                account.initial_cash * Decimal("0.01"),
                account.initial_cash * Decimal("0.02") - event_cost - event_reserved,
            )
        )
        limit_price = min(Decimal("0.999999"), money(quote.asks[0].price * Decimal("1.005")))
        unit_cost = limit_price + (quote.fee_rate or ZERO) * limit_price * (1 - limit_price)
        quantity = min(
            Decimal(2000),
            (max(budget - Decimal("0.01"), ZERO) / unit_cost).to_integral_value(
                rounding=ROUND_DOWN
            ),
        )
        if budget <= 0 or quantity < 1:
            action, reason = "WAIT", "capital_or_event_limit"
    elif action == "SELL" and quote and position:
        quantity = position.quantity
        limit_price = max(Decimal("0.000001"), money(quote.bids[0].price * Decimal("0.98")))
    if (
        automatic
        and action == "BUY"
        and quote
        and account.strategy in {"momentum", "agent_filtered"}
    ):
        opportunity = opportunity or reviews.opportunity_for(account, target, quote, now)
        if account.strategy == "agent_filtered":
            action, reason, agent_run = reviews.gate(opportunity, target, quote, now)
    inputs = {
        "version": account.experiment.version,
        "opportunity_id": str(opportunity.id) if opportunity else None,
        "policy": account.experiment.settings,
        "observation": market.latest,
        "metrics": market.metrics,
        "quote": quote.model_dump(mode="json", exclude={"raw"}) if quote else None,
        "agent_report": agent_run.report if agent_run else None,
        "agent_finished_at": agent_run.finished_at.isoformat()
        if agent_run and agent_run.finished_at
        else None,
    }
    decision = Decision.objects.create(
        account=account,
        market=market,
        observation_id=observation_id,
        created_at=now,
        action=action,
        reason=reason,
        inputs=inputs,
        agent_run=agent_run,
        phase=phase,
        opportunity=opportunity,
    )
    if opportunity and account.strategy == "agent_filtered" and phase == "REVIEW":
        opportunity.agent_decision = decision
        opportunity.state = {
            "review_allowed": "ALLOWED",
            "review_rejected": "REJECTED",
            "review_abstained": "ABSTAINED",
            "review_failed": "FAILED",
        }.get(reason, "INVALIDATED")
        opportunity.reason = reason
        opportunity.save(update_fields=["agent_decision", "state", "reason"])
    if action in {"BUY", "SELL"}:
        Order.objects.create(
            account=account,
            market=market,
            decision=decision,
            side=action,
            quantity=quantity,
            limit_price=limit_price,
            budget=budget,
            eligible_at=now + timedelta(seconds=2),
            expires_at=now + timedelta(seconds=120),
        )
