import uuid

from django.conf import settings
from django.db import models


class Experiment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=120, default="Paper trading experiment")
    running = models.BooleanField(default=True)
    version = models.CharField(max_length=30, default="paper-v1")
    settings = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    checked_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "version"], name="paper_version_unique"
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(running=True),
                name="paper_one_running_per_org",
            ),
        ]


class ExperimentMarket(models.Model):
    experiment = models.ForeignKey(Experiment, on_delete=models.PROTECT, related_name="universe")
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    rules_version = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["experiment", "market"], name="paper_universe_unique")
        ]


class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    experiment = models.ForeignKey(Experiment, on_delete=models.PROTECT, related_name="accounts")
    platform = models.CharField(max_length=20)
    strategy = models.CharField(max_length=30)
    initial_cash = models.DecimalField(max_digits=20, decimal_places=6, default=10000)
    cash = models.DecimalField(max_digits=20, decimal_places=6, default=10000)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    fees = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    high_water = models.DecimalField(max_digits=20, decimal_places=6, default=10000)
    max_drawdown = models.DecimalField(max_digits=12, decimal_places=8, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "platform", "strategy"], name="paper_account_unique"
            ),
            models.CheckConstraint(condition=models.Q(cash__gte=0), name="paper_cash_nonnegative"),
        ]


class Decision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="decisions")
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    observation_id = models.UUIDField()
    created_at = models.DateTimeField()
    action = models.CharField(max_length=10)
    reason = models.CharField(max_length=80)
    inputs = models.JSONField(default=dict)
    agent_run = models.ForeignKey("agents.AgentRun", null=True, on_delete=models.PROTECT)
    phase = models.CharField(max_length=10, default="SIGNAL")
    opportunity = models.ForeignKey(
        "Opportunity", null=True, on_delete=models.PROTECT, related_name="decisions"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "market", "observation_id", "phase"],
                name="paper_decision_phase_unique",
            )
        ]


class Opportunity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    experiment = models.ForeignKey(
        Experiment, on_delete=models.PROTECT, related_name="opportunities"
    )
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    observation_id = models.UUIDField()
    detected_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    inputs = models.JSONField()
    state = models.CharField(max_length=15, default="WAITING")
    reason = models.CharField(max_length=80, default="review_pending")
    review_run = models.OneToOneField(
        "agents.AgentRun", null=True, on_delete=models.PROTECT, related_name="paper_opportunity"
    )
    agent_decision = models.OneToOneField(
        Decision, null=True, on_delete=models.PROTECT, related_name="applied_review"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "market", "observation_id"], name="paper_opportunity_unique"
            ),
            models.UniqueConstraint(
                fields=["experiment", "market"],
                condition=models.Q(state="WAITING"),
                name="paper_one_waiting_opportunity",
            ),
        ]
        indexes = [models.Index(fields=["experiment", "state", "detected_at"])]


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="orders")
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    decision = models.OneToOneField(Decision, on_delete=models.PROTECT)
    side = models.CharField(max_length=4)
    status = models.CharField(max_length=12, default="PENDING")
    reason = models.CharField(max_length=80, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    filled_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    limit_price = models.DecimalField(max_digits=12, decimal_places=6)
    budget = models.DecimalField(max_digits=20, decimal_places=6)
    eligible_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True)
    execution_quote = models.JSONField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "market"],
                condition=models.Q(status="PENDING"),
                name="paper_one_pending_per_market",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="paper_order_positive_quantity"
            ),
        ]


class Position(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="positions")
    market = models.ForeignKey("markets.Market", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    cost_basis = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True)
    settlement_quote = models.JSONField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "market"], name="paper_position_unique"),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="paper_position_nonnegative"
            ),
        ]


class LedgerEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="ledger")
    order = models.ForeignKey(Order, null=True, on_delete=models.PROTECT, related_name="fills")
    market = models.ForeignKey("markets.Market", null=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    price = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    fee = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    cash_delta = models.DecimalField(max_digits=20, decimal_places=6)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    quote_id = models.UUIDField(null=True)
    created_at = models.DateTimeField()


class EquitySnapshot(models.Model):
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="equity")
    at = models.DateTimeField()
    cash = models.DecimalField(max_digits=20, decimal_places=6)
    equity = models.DecimalField(max_digits=20, decimal_places=6, null=True)
    unrealized_pnl = models.DecimalField(max_digits=20, decimal_places=6, null=True)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6)
    fees = models.DecimalField(max_digits=20, decimal_places=6)
    unpriced_positions = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "at"], name="paper_equity_unique")
        ]
        indexes = [models.Index(fields=["account", "at"])]
