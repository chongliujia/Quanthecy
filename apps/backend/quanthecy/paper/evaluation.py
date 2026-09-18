from uuid import UUID

from django.db.models import (
    Avg,
    BooleanField,
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone

from quanthecy.accounts.models import User
from quanthecy.agents.models import AgentRun
from quanthecy.agents.services import runs_today, status
from quanthecy.organizations.policies import require_org_member

from .models import Account, Experiment, Opportunity, Order
from .schemas import ReviewDetail, ReviewOut, ReviewSummary


def with_entry_counts(query: QuerySet[Opportunity]) -> QuerySet[Opportunity]:
    orders = Order.objects.filter(
        decision__opportunity_id=OuterRef("pk"), side="BUY", filled_quantity__gt=0
    )
    baseline = Order.objects.filter(
        account__experiment_id=OuterRef("experiment_id"),
        account__strategy="momentum",
        market_id=OuterRef("market_id"),
        decision__observation_id=OuterRef("observation_id"),
        side="BUY",
        filled_quantity__gt=0,
    )
    return query.annotate(
        baseline_filled_flag=Case(
            When(account__isnull=True, then=Exists(orders.filter(account__strategy="momentum"))),
            default=Exists(baseline),
            output_field=BooleanField(),
        ),
        agent_filled_flag=Exists(
            orders.filter(account__strategy__in=["agent_filtered", "assistant"])
        ),
    )


def filled(op: Opportunity, strategy: str) -> bool:
    if strategy == "momentum":
        if op.account_id is None:
            return Order.objects.filter(
                decision__opportunity=op,
                account__strategy="momentum",
                side="BUY",
                filled_quantity__gt=0,
            ).exists()
        return Order.objects.filter(
            account__experiment=op.experiment,
            account__strategy="momentum",
            market_id=op.market_id,
            decision__observation_id=op.observation_id,
            side="BUY",
            filled_quantity__gt=0,
        ).exists()
    return Order.objects.filter(
        decision__opportunity=op,
        account__strategy__in=["agent_filtered", "assistant"],
        side="BUY",
        filled_quantity__gt=0,
    ).exists()


def review_summary(op: Opportunity) -> ReviewOut:
    run = op.review_run
    version = op.account.assistant_version if op.account is not None else None
    return ReviewOut(
        id=op.id,
        account_id=op.account_id,
        assistant_label=(f"{version.name} · v{version.number}") if version is not None else "",
        run_id=run.id if run else None,
        market_id=op.market_id,
        title=op.market.title,
        detected_at=op.detected_at,
        expires_at=op.expires_at,
        state=op.state,
        reason=op.reason,
        run_state=run.state if run else None,
        review_decision=run.report.get("decision") if run and run.report else None,
        model=run.model if run else None,
        error_code=run.error_code if run else "",
        baseline_filled=op.baseline_filled_flag
        if hasattr(op, "baseline_filled_flag")
        else filled(op, "momentum"),
        agent_filled=op.agent_filled_flag
        if hasattr(op, "agent_filled_flag")
        else filled(op, "agent_filtered"),
    )


def evaluation(
    actor: User, experiment: Experiment, account: Account | None = None
) -> ReviewSummary:
    # The capability is workspace configuration; VIEWER status does not make it unavailable.
    model = status(actor, experiment.organization_id)
    ops = experiment.opportunities.all()
    runs = AgentRun.objects.filter(paper_opportunity__experiment=experiment)
    if account:
        ops = ops.filter(account=account)
        runs = runs.filter(paper_opportunity__account=account)
    counts = ops.aggregate(
        candidates=Count("id"),
        invalidated=Count("id", filter=Q(state__in=["INVALIDATED", "EXPIRED", "PAUSED"])),
        waiting=Count("id", filter=Q(state="WAITING")),
        latency=Avg(
            F("review_run__finished_at") - F("detected_at"), filter=Q(review_run__state="SUCCEEDED")
        ),
    )
    reviews = runs.aggregate(
        reviewed=Count("id", filter=Q(state="SUCCEEDED")),
        allowed=Count("id", filter=Q(state="SUCCEEDED", report__decision="ALLOW")),
        rejected=Count("id", filter=Q(state="SUCCEEDED", report__decision="REJECT")),
        abstained=Count("id", filter=Q(state="SUCCEEDED", report__decision="WAIT")),
        failed=Count("id", filter=Q(state__in=["FAILED", "CANCELLED"])),
        queue=Avg(F("started_at") - F("created_at")),
        **{
            name: Coalesce(Sum(Cast("usage__" + name, IntegerField())), Value(0))
            for name in ["provider_calls", "prompt_tokens", "completion_tokens"]
        },
    )
    matched = with_entry_counts(ops.all()).aggregate(
        paired=Count("id", filter=Q(baseline_filled_flag=True)),
        joined=Count("id", filter=Q(baseline_filled_flag=True, agent_filled_flag=True)),
    )
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    calls_today = AgentRun.objects.filter(
        organization_id=experiment.organization_id, kind="PAPER_REVIEW", created_at__gte=today
    ).count()
    limit = experiment.settings["daily_review_limit"]
    return ReviewSummary(
        model_ready=bool(model.enabled and model.model and not model.configuration_issue),
        model=model.model,
        daily_limit=limit,
        calls_today=calls_today,
        calls_remaining=max(
            0,
            min(
                limit - calls_today, model.daily_run_limit - runs_today(experiment.organization_id)
            ),
        ),
        candidates=counts["candidates"],
        reviewed=reviews["reviewed"],
        allowed=reviews["allowed"],
        rejected=reviews["rejected"],
        abstained=reviews["abstained"],
        invalidated=counts["invalidated"],
        failed=reviews["failed"],
        waiting=counts["waiting"],
        paired_candidates=matched["paired"],
        paired_agent_entries=matched["joined"],
        participation=matched["joined"] / matched["paired"] if matched["paired"] else None,
        provider_calls=reviews["provider_calls"],
        prompt_tokens=reviews["prompt_tokens"],
        completion_tokens=reviews["completion_tokens"],
        average_latency_seconds=counts["latency"].total_seconds()
        if counts["latency"] is not None
        else None,
        average_queue_seconds=reviews["queue"].total_seconds()
        if reviews["queue"] is not None
        else None,
    )


def review_detail(actor: User, organization_id: UUID, opportunity_id: UUID) -> ReviewDetail:
    require_org_member(actor, organization_id)
    op = get_object_or_404(
        Opportunity.objects.select_related("review_run", "market"),
        id=opportunity_id,
        experiment__organization_id=organization_id,
    )
    run = op.review_run
    return ReviewDetail(
        **review_summary(op).model_dump(),
        inputs=op.inputs,
        context={k: v for k, v in run.context.items() if k != "observations"} if run else None,
        report=run.report if run else None,
        usage=run.usage if run else {},
        finished_at=run.finished_at if run else None,
    )
