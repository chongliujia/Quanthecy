import json
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from quanthecy_analytics.paper import ZERO, ExecutionQuote, match_order
from redis import Redis

from quanthecy.accounts.models import User
from quanthecy.organizations.policies import require_org_member

from .evaluation import evaluation, review_detail, review_summary, with_entry_counts  # noqa: F401
from .models import Experiment, Order
from .schemas import (
    AccountOut,
    DecisionOut,
    EquityOut,
    ExperimentOut,
    FillOut,
    LabOut,
    OrderDetail,
    OrderOut,
    PositionOut,
)


def order_summary(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "account_id": order.account_id,
        "market_id": order.market_id,
        "title": order.market.title,
        "side": order.side,
        "status": order.status,
        "reason": order.reason,
        "quantity": order.quantity,
        "filled_quantity": order.filled_quantity,
        "limit_price": order.limit_price,
        "created_at": order.decision.created_at,
        "finished_at": order.finished_at,
    }


def lab(actor: User, organization_id: UUID, experiment_id: UUID | None = None) -> LabOut | None:
    require_org_member(actor, organization_id)
    experiments = list(
        Experiment.objects.filter(organization_id=organization_id).order_by(
            "-created_at", "-version", "-id"
        )
    )
    experiment = (
        get_object_or_404(Experiment, organization_id=organization_id, id=experiment_id)
        if experiment_id
        else (experiments[0] if experiments else None)
    )
    if experiment is None:
        return None
    collector: dict[str, Any] = {}
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
        ) as cache:
            raw = cache.get("paper:collector:status:v1")
        if isinstance(raw, (bytes, str)) and len(raw) <= 4096:
            collector = json.loads(raw)
    except Exception:
        pass
    accounts = []
    positions: list[PositionOut] = []
    for account in experiment.accounts.order_by("platform", "strategy"):
        latest = account.equity.order_by("-at").first()
        reserve = (
            account.orders.filter(status="PENDING", side="BUY").aggregate(value=Sum("budget"))[
                "value"
            ]
            or ZERO
        )
        history = list(account.equity.order_by("-at")[:720])
        accounts.append(
            AccountOut(
                id=account.id,
                platform=account.platform,
                strategy=account.strategy,
                initial_cash=account.initial_cash,
                cash=account.cash,
                reserved_cash=reserve,
                equity=latest.equity if latest else None,
                realized_pnl=account.realized_pnl,
                unrealized_pnl=latest.unrealized_pnl if latest else None,
                fees=account.fees,
                max_drawdown=account.max_drawdown,
                unpriced_positions=latest.unpriced_positions if latest else 0,
                equity_at=latest.at if latest else None,
                fills=account.ledger.filter(kind__in=["BUY", "SELL"]).count(),
                orders=account.orders.count(),
                equity_history=[
                    EquityOut(at=row.at, equity=row.equity) for row in reversed(history)
                ],
            )
        )
        positions.extend(
            PositionOut(
                id=p.id,
                account_id=account.id,
                market_id=p.market_id,
                title=p.market.title,
                quantity=p.quantity,
                cost_basis=p.cost_basis,
                opened_at=p.opened_at,
            )
            for p in account.positions.filter(quantity__gt=0).select_related("market")
        )
    orders = (
        Order.objects.filter(account__experiment=experiment)
        .select_related("market", "decision")
        .order_by("-decision__created_at", "-id")[:50]
    )
    decisions = experiment.accounts.values_list("id", flat=True)
    from .models import Decision

    recent = (
        Decision.objects.filter(account_id__in=decisions)
        .select_related("market")
        .order_by("-created_at", "-id")[:60]
    )
    return LabOut(
        experiments=[
            ExperimentOut(
                id=e.id, name=e.name, version=e.version, running=e.running, created_at=e.created_at
            )
            for e in experiments
        ],
        is_latest=experiment.id == experiments[0].id,
        review_summary=evaluation(actor, experiment) if experiment.version == "paper-v2" else None,
        recent_reviews=[
            review_summary(o)
            for o in with_entry_counts(
                experiment.opportunities.select_related("market", "review_run")
            ).order_by("-detected_at")[:20]
        ],
        id=experiment.id,
        name=experiment.name,
        running=experiment.running,
        version=experiment.version,
        settings=experiment.settings,
        checked_at=experiment.checked_at,
        created_at=experiment.created_at,
        error_code=experiment.error_code,
        collector=collector,
        market_count=experiment.universe.count(),
        accounts=accounts,
        positions=positions,
        recent_orders=[OrderOut(**order_summary(o)) for o in orders],
        recent_decisions=[
            DecisionOut(
                id=d.id,
                account_id=d.account_id,
                market_id=d.market_id,
                title=d.market.title,
                action=d.action,
                reason=d.reason,
                created_at=d.created_at,
            )
            for d in recent
        ],
    )


def order_detail(actor: User, organization_id: UUID, order_id: UUID) -> OrderDetail:
    require_org_member(actor, organization_id)
    order = get_object_or_404(
        Order.objects.select_related("market", "decision"),
        id=order_id,
        account__experiment__organization_id=organization_id,
    )
    rows = list(order.fills.order_by("created_at", "id"))
    replay = None
    if order.execution_quote is not None:
        quote = ExecutionQuote.model_validate(order.execution_quote)
        simulated = match_order(
            quote=quote,
            side="BUY" if order.side == "BUY" else "SELL",
            quantity=order.quantity,
            limit_price=order.limit_price,
            budget=order.budget,
        )
        expected = sorted((f.quantity, f.price, f.fee) for f in simulated)
        actual = sorted((f.quantity, f.price, f.fee) for f in rows)
        replay = actual == expected
    return OrderDetail(
        **order_summary(order),
        inputs=order.decision.inputs,
        execution_quote=order.execution_quote,
        fills=[
            FillOut(
                quantity=f.quantity,
                price=f.price,
                fee=f.fee,
                cash_delta=f.cash_delta,
                realized_pnl=f.realized_pnl,
                quote_id=f.quote_id,
                created_at=f.created_at,
            )
            for f in rows
        ],
        replay_matches=replay,
    )
