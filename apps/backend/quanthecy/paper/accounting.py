from datetime import datetime
from decimal import Decimal
from uuid import UUID

from quanthecy_analytics.paper import ZERO, ExecutionQuote, match_order, money, quote_issue

from .models import Account, EquitySnapshot, LedgerEntry, Order, Position


def execute_order(
    order: Order, account: Account, quote: ExecutionQuote | None, now: datetime
) -> None:
    if now >= order.expires_at:
        order.status, order.reason = "EXPIRED", "no_eligible_fill_before_expiry"
    elif quote is None or quote.received_at < order.eligible_at or quote.received_at > now:
        return
    elif quote_issue(quote, now):
        order.reason = quote_issue(quote, now)
        order.save(update_fields=["reason"])
        return
    else:
        position = Position.objects.filter(account=account, market=order.market).first()
        available = position.quantity if position else ZERO
        quantity = min(order.quantity, available) if order.side == "SELL" else order.quantity
        fills = match_order(
            quote=quote,
            side="BUY" if order.side == "BUY" else "SELL",
            quantity=quantity,
            limit_price=order.limit_price,
            budget=min(order.budget, account.cash),
        )
        order.execution_quote = quote.model_dump(mode="json", exclude={"raw"})
        for fill in fills:
            notional = money(fill.quantity * fill.price)
            realized = ZERO
            if order.side == "BUY":
                if position is None:
                    position = Position.objects.create(
                        account=account, market=order.market, opened_at=now
                    )
                elif position.quantity == 0:
                    position.opened_at, position.closed_at = now, None
                    position.settlement_quote = None
                delta = -(notional + fill.fee)
                position.quantity += fill.quantity
                position.cost_basis += -delta
            else:
                if position is None or position.quantity < fill.quantity:
                    raise ValueError("Paper position cannot be oversold")
                basis = (
                    position.cost_basis
                    if fill.quantity == position.quantity
                    else money(position.cost_basis * fill.quantity / position.quantity)
                )
                delta = notional - fill.fee
                realized = delta - basis
                position.quantity -= fill.quantity
                position.cost_basis -= basis
                if position.quantity == 0:
                    position.closed_at = now
            account.cash += delta
            account.realized_pnl += realized
            account.fees += fill.fee
            position.save()
            LedgerEntry.objects.create(
                account=account,
                order=order,
                market=order.market,
                kind=order.side,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                cash_delta=delta,
                realized_pnl=realized,
                quote_id=quote.quote_id,
                created_at=now,
            )
            order.filled_quantity += fill.quantity
        order.status = (
            "FILLED"
            if order.filled_quantity == order.quantity
            else "PARTIAL"
            if fills
            else "UNFILLED"
        )
        order.reason = "snapshot_ioc" if fills else "insufficient_depth_or_price_limit"
        account.save()
    order.finished_at = now
    order.save()


def settle(account: Account, quotes: dict[UUID, ExecutionQuote], now: datetime) -> None:
    for position in account.positions.filter(quantity__gt=0).select_related("market"):
        quote = quotes.get(position.market_id)
        if quote is None or quote.status != "RESOLVED" or quote.settlement is None:
            continue
        if quote.recorded_at > now or not 0 <= (now - quote.received_at).total_seconds() <= 90:
            continue
        price = Decimal(quote.settlement)
        proceeds = money(position.quantity * price)
        realized = proceeds - position.cost_basis
        LedgerEntry.objects.create(
            account=account,
            market=position.market,
            kind="SETTLEMENT",
            quantity=position.quantity,
            price=price,
            cash_delta=proceeds,
            realized_pnl=realized,
            quote_id=quote.quote_id,
            created_at=now,
        )
        account.cash += proceeds
        account.realized_pnl += realized
        position.quantity, position.cost_basis, position.closed_at = ZERO, ZERO, now
        position.settlement_quote = quote.model_dump(mode="json", exclude={"raw"})
        position.save()
        account.orders.filter(market=position.market, status="PENDING").update(
            status="CANCELLED", reason="market_settled", finished_at=now
        )
    account.save()


def mark_equity(account: Account, quotes: dict[UUID, ExecutionQuote], now: datetime) -> None:
    # One sample per minute; nulls preserve unavailable liquidation estimates.
    at = now.replace(second=0, microsecond=0)
    if account.equity.filter(at=at).exists():
        return
    equity, basis, unpriced = account.cash, ZERO, 0
    for position in account.positions.filter(quantity__gt=0):
        basis += position.cost_basis
        quote = quotes.get(position.market_id)
        if quote is None or quote_issue(quote, now):
            unpriced += 1
            continue
        fills = match_order(
            quote=quote,
            side="SELL",
            quantity=position.quantity,
            limit_price=Decimal("0.000001"),
            budget=ZERO,
        )
        if sum((fill.quantity for fill in fills), ZERO) != position.quantity:
            unpriced += 1
            continue
        equity += sum((money(fill.quantity * fill.price) - fill.fee for fill in fills), ZERO)
    if not unpriced:
        account.high_water = max(account.high_water, equity)
        account.max_drawdown = max(
            account.max_drawdown, (account.high_water - equity) / account.high_water
        )
        account.save(update_fields=["high_water", "max_drawdown"])
    EquitySnapshot.objects.create(
        account=account,
        at=at,
        cash=account.cash,
        equity=None if unpriced else equity,
        unrealized_pnl=None if unpriced else equity - account.cash - basis,
        realized_pnl=account.realized_pnl,
        fees=account.fees,
        unpriced_positions=unpriced,
    )
