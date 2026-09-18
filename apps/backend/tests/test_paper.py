import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from quanthecy.accounts.models import User
from quanthecy.agents.models import AgentRun
from quanthecy.markets.models import CollectionTarget, Event, Market, ResearchTopic
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.services import create_organization
from quanthecy.paper.models import Account, Decision, Experiment, LedgerEntry, Order, Position
from quanthecy.paper.services import create_experiment, set_running
from quanthecy.paper.views import order_detail
from quanthecy.paper.worker import process_experiment
from quanthecy_analytics.paper import ExecutionQuote, fee, match_order
from quanthecy_analytics.quality import VERSION as QUALITY_VERSION

pytestmark = pytest.mark.django_db
BASE = datetime(2026, 9, 18, 12, tzinfo=UTC)
TEMPLATE = json.loads(
    (Path(__file__).resolve().parents[3] / "tests/fixtures/polymarket/observation.json").read_text()
)


@pytest.fixture
def setup():
    user = User.objects.create_user("paper@example.com", "test-pass-123")
    org = create_organization(owner=user, name="Paper research")
    event = Event.objects.create(
        platform="polymarket", exchange_id="event", title="An event", observed_at=BASE
    )
    data = copy.deepcopy(TEMPLATE)
    mid = uuid4()
    data.update(
        observation_id=str(uuid4()), received_at=BASE.isoformat(), recorded_at=BASE.isoformat()
    )
    data["market"].update(
        id=str(mid),
        exchange_id="123",
        rules_version="rules-v1",
        closes_at="2027-01-01T00:00:00Z",
        status="OPEN",
    )
    data["outcome"]["exchange_id"] = "456"
    data.update(best_bid=0.49, best_ask=0.5)
    market = Market.objects.create(
        id=mid,
        event=event,
        platform="polymarket",
        exchange_id="123",
        title="Test market",
        status="OPEN",
        first_observed_at=BASE - timedelta(hours=1),
        last_observed_at=BASE,
        latest=data,
        probability_change_15m=0.03,
        metrics={"quality": {"version": QUALITY_VERSION, "price_usable": True}},
    )
    topic = ResearchTopic.objects.create(slug="paper-fixture", name="Fixture")
    CollectionTarget.objects.create(
        topic=topic, platform="polymarket", exchange_id="123", label="Fixture", rationale="Test"
    )
    with patch("quanthecy.paper.services.timezone.now", return_value=BASE):
        experiment = create_experiment(user, org.id, [market.id], Decimal(10000), "Experiment")
    return user, org, market, experiment


def quote(market, at=BASE, **changes):
    value = dict(
        schema_version=1,
        quote_id=uuid4(),
        market_id=market.id,
        platform=market.platform,
        exchange_id=market.exchange_id,
        outcome_id=market.latest["outcome"]["exchange_id"],
        received_at=at,
        recorded_at=at,
        metadata_at=at,
        source_at=None,
        status="OPEN",
        settlement=None,
        bids=[{"price": "0.49", "size": "10000"}],
        asks=[{"price": "0.50", "size": "10000"}],
        fee_rate="0.03",
        fee_model="polymarket_quadratic",
        fee_source="https://example.test/fees",
        source="https://example.test/book",
        raw={},
    )
    value.update(changes)
    return ExecutionQuote.model_validate(value)


def cycle(experiment, market, at, **changes):
    q = quote(market, at, **changes)
    process_experiment(experiment.id, {market.id: q}, at)
    return q


def momentum(experiment):
    return Account.objects.get(experiment=experiment, strategy="momentum")


def test_cannot_fill_at_decision_time_or_reuse_quotes_and_ledger_balances(setup):
    user, org, market, experiment = setup
    q = cycle(experiment, market, BASE)
    assert Order.objects.count() == 2  # Momentum and benchmark; Agent abstains.
    assert not LedgerEntry.objects.filter(kind="BUY").exists()
    process_experiment(experiment.id, {market.id: q}, BASE + timedelta(seconds=1))
    assert not LedgerEntry.objects.filter(kind="BUY").exists()
    cycle(experiment, market, BASE + timedelta(seconds=3))
    account = momentum(experiment)
    order = account.orders.get()
    assert order.status == "FILLED"
    assert order.execution_quote["quote_id"] != str(q.quote_id)
    assert order.execution_quote["received_at"] > order.decision.created_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert order.filled_quantity > 0
    assert sum(account.ledger.values_list("cash_delta", flat=True)) == account.cash
    assert account.positions.get().cost_basis + account.cash == account.initial_cash
    assert account.fees > 0
    count = LedgerEntry.objects.count()
    cycle(experiment, market, BASE + timedelta(seconds=4))
    assert LedgerEntry.objects.count() == count
    assert order_detail(user, org.id, order.id).replay_matches is True


def test_partial_ioc_never_invents_depth_and_cancels_remainder(setup):
    _, _, market, experiment = setup
    cycle(experiment, market, BASE)
    cycle(experiment, market, BASE + timedelta(seconds=3), asks=[{"price": "0.50", "size": "25"}])
    order = momentum(experiment).orders.get()
    assert order.status == "PARTIAL" and order.filled_quantity == 2
    cycle(experiment, market, BASE + timedelta(seconds=30))
    order.refresh_from_db()
    assert order.filled_quantity == 2


def test_unknown_fees_stale_books_and_future_books_block_fills(setup):
    _, _, market, experiment = setup
    cycle(experiment, market, BASE, fee_rate=None, fee_model="unknown")
    assert not Order.objects.exists()
    assert set(Decision.objects.values_list("reason", flat=True)) == {"unknown_fees"}


def test_pending_expiry_and_pause_leave_no_cash_movements(setup):
    user, org, market, experiment = setup
    cycle(experiment, market, BASE)
    process_experiment(experiment.id, {}, BASE + timedelta(seconds=121))
    assert set(Order.objects.values_list("status", flat=True)) == {"EXPIRED"}
    assert LedgerEntry.objects.exclude(kind="DEPOSIT").count() == 0
    set_running(user, org.id, False)
    cycle(experiment, market, BASE + timedelta(minutes=6))
    assert Order.objects.count() == 2


def test_future_agent_report_is_not_used_and_other_workspace_reports_are_isolated(setup):
    user, org, market, experiment = setup
    report = {"action": "INVESTIGATE", "risk_flags": [], "confidence": 0.99}
    AgentRun.objects.create(
        organization=org,
        requested_by=user,
        market=market,
        idempotency_key=uuid4(),
        cutoff=BASE,
        configuration_revision=1,
        provider="local",
        model="test",
        state="SUCCEEDED",
        finished_at=BASE + timedelta(seconds=1),
        report=report,
    )
    cycle(experiment, market, BASE)
    assert (
        Account.objects.get(experiment=experiment, strategy="agent_filtered").decisions.get().reason
        == "awaiting_agent_report"
    )


def test_agent_risk_filter_runs_only_after_numeric_entry_and_never_uses_confidence_as_probability(
    setup,
):
    user, org, market, experiment = setup
    AgentRun.objects.create(
        organization=org,
        requested_by=user,
        market=market,
        idempotency_key=uuid4(),
        cutoff=BASE - timedelta(minutes=1),
        configuration_revision=1,
        provider="local",
        model="test",
        state="SUCCEEDED",
        finished_at=BASE - timedelta(seconds=1),
        report={"action": "WATCH", "risk_flags": [], "confidence": 0.01},
    )
    cycle(experiment, market, BASE)
    assert Account.objects.get(experiment=experiment, strategy="agent_filtered").orders.count() == 1


def test_sell_realizes_entry_cost_and_settlement_pays_once(setup):
    _, _, market, experiment = setup
    cycle(experiment, market, BASE)
    cycle(experiment, market, BASE + timedelta(seconds=3))
    market.last_observed_at = BASE + timedelta(hours=1, seconds=4)
    market.latest["observation_id"] = str(uuid4())
    market.save()
    cycle(experiment, market, BASE + timedelta(hours=1, seconds=4))
    cycle(
        experiment,
        market,
        BASE + timedelta(hours=1, seconds=7),
        bids=[{"price": "0.60", "size": "10000"}],
        asks=[{"price": "0.61", "size": "10000"}],
    )
    account = momentum(experiment)
    assert account.positions.get().quantity == 0
    assert account.cash - account.initial_cash == account.realized_pnl
    assert account.realized_pnl > 0
    cycle(
        experiment,
        market,
        BASE + timedelta(hours=1, seconds=8),
        status="RESOLVED",
        settlement=1,
        bids=[],
        asks=[],
    )
    baseline = Account.objects.get(experiment=experiment, strategy="buy_hold")
    cash = baseline.cash
    cycle(
        experiment,
        market,
        BASE + timedelta(hours=1, seconds=9),
        status="RESOLVED",
        settlement=1,
        bids=[],
        asks=[],
    )
    baseline.refresh_from_db()
    assert baseline.cash == cash
    assert baseline.ledger.filter(kind="SETTLEMENT").count() == 1


def test_missing_valuation_is_null_not_zero_or_fictitious_profit(setup):
    _, _, market, experiment = setup
    cycle(experiment, market, BASE)
    cycle(experiment, market, BASE + timedelta(seconds=3))
    process_experiment(experiment.id, {}, BASE + timedelta(minutes=2))
    point = momentum(experiment).equity.latest("at")
    assert point.equity is None and point.unrealized_pnl is None and point.unpriced_positions == 1


def test_org_isolation_readonly_viewers_and_csrf(setup):
    user, org, market, experiment = setup
    cycle(experiment, market, BASE)
    other = User.objects.create_superuser("other@example.com", "test-pass-123")
    client = Client()
    client.force_login(other)
    assert client.get(f"/api/v1/organizations/{org.id}/paper").status_code == 404
    order = Order.objects.first()
    assert client.get(f"/api/v1/organizations/{org.id}/paper/orders/{order.id}").status_code == 404
    OrganizationMembership.objects.create(user=other, organization=org, role="VIEWER")
    with patch("quanthecy.paper.views.Redis.from_url", side_effect=OSError):
        assert client.get(f"/api/v1/organizations/{org.id}/paper").status_code == 200
    with pytest.raises(PermissionDenied):
        set_running(other, org.id, False)
    secure = Client(enforce_csrf_checks=True)
    secure.force_login(user)
    assert (
        secure.patch(
            f"/api/v1/organizations/{org.id}/paper",
            data=json.dumps({"running": False}),
            content_type="application/json",
        ).status_code
        == 403
    )


def test_transaction_rolls_back_fills_if_account_processing_fails(setup):
    _, _, market, experiment = setup
    cycle(experiment, market, BASE)
    with (
        patch("quanthecy.paper.worker.mark_equity", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        cycle(experiment, market, BASE + timedelta(seconds=3))
    assert not LedgerEntry.objects.filter(kind="BUY").exists()
    assert set(Order.objects.values_list("status", flat=True)) == {"PENDING"}


def test_fee_rounding_and_cash_budget_at_multiple_depth_levels(setup):
    _, _, market, _ = setup
    q = quote(
        market,
        fee_rate="0.07",
        fee_model="kalshi_quadratic",
        asks=[{"price": "0.50", "size": "30"}, {"price": "0.51", "size": "10000"}],
    )
    assert fee(Decimal(1), Decimal("0.50"), q) == Decimal("0.02")
    fills = match_order(
        quote=q, side="BUY", quantity=Decimal(100), limit_price=Decimal("0.52"), budget=Decimal(10)
    )
    assert fills[0].quantity == 3
    assert sum(f.quantity * f.price + f.fee for f in fills) <= 10
    assert len(fills) == 2


def test_duplicate_universe_and_experiment_creation_are_rejected(setup):
    user, org, market, _ = setup
    with pytest.raises(ValidationError):
        create_experiment(user, org.id, [market.id], Decimal(10000), "Duplicate")
    assert Experiment.objects.count() == 1


@pytest.mark.parametrize("offset", [-91, 1])
def test_stale_and_future_books_cannot_trigger_orders(setup, offset):
    _, _, market, experiment = setup
    q = quote(market, BASE + timedelta(seconds=offset))
    process_experiment(experiment.id, {market.id: q}, BASE)
    assert not Order.objects.exists()
    assert set(Decision.objects.values_list("reason", flat=True)) == {"stale_orderbook"}


def test_future_persistence_and_unknown_settlement_do_not_create_cash(setup):
    _, _, market, experiment = setup
    cycle(experiment, market, BASE)
    cycle(experiment, market, BASE + timedelta(seconds=3), recorded_at=BASE + timedelta(seconds=4))
    assert not LedgerEntry.objects.filter(kind="BUY").exists()
    cycle(experiment, market, BASE + timedelta(seconds=5))
    cycle(
        experiment,
        market,
        BASE + timedelta(seconds=8),
        status="RESOLVED",
        settlement=None,
        bids=[],
        asks=[],
    )
    assert not LedgerEntry.objects.filter(kind="SETTLEMENT").exists()
    assert Position.objects.filter(quantity__gt=0).count() == 2


def test_other_workspace_agent_report_does_not_authorize_entry(setup):
    user, _, market, experiment = setup
    org = create_organization(owner=user, name="Another workspace")
    AgentRun.objects.create(
        organization=org,
        requested_by=user,
        market=market,
        idempotency_key=uuid4(),
        cutoff=BASE - timedelta(minutes=1),
        configuration_revision=1,
        provider="local",
        model="test",
        state="SUCCEEDED",
        finished_at=BASE - timedelta(seconds=1),
        report={"action": "WATCH", "risk_flags": []},
    )
    cycle(experiment, market, BASE)
    account = Account.objects.get(experiment=experiment, strategy="agent_filtered")
    assert account.decisions.get().reason == "awaiting_agent_report"
    assert not account.orders.exists()


def test_pause_cancels_existing_orders_and_changed_rules_block_execution(setup):
    user, org, market, experiment = setup
    cycle(experiment, market, BASE)
    market.latest["market"]["rules_version"] = "changed"
    market.save()
    cycle(experiment, market, BASE + timedelta(seconds=3))
    assert set(Order.objects.values_list("reason", flat=True)) == {"rules_changed"}
    assert not LedgerEntry.objects.filter(kind="BUY").exists()
    # Pause must also cancel any other pending orders before a worker can fill them.
    Order.objects.update(status="PENDING")
    set_running(user, org.id, False)
    cycle(experiment, market, BASE + timedelta(seconds=5))
    assert set(Order.objects.values_list("reason", flat=True)) == {"experiment_paused"}
    assert not LedgerEntry.objects.filter(kind="BUY").exists()
