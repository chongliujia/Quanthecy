from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from quanthecy_analytics.intelligence import SKILLS, VERSION, Language, Workflow

from quanthecy.accounts.models import User
from quanthecy.markets.models import Market
from quanthecy.organizations.models import Organization
from quanthecy.organizations.policies import require_org_member, require_org_role
from quanthecy.research.services import cutoff_time

from .catalog import DEFAULT_ENDPOINTS
from .configuration import decrypt_key, endpoint, validate_local_limits, validate_model_target
from .models import AgentRun, Assistant, ModelConfiguration
from .schemas import AgentStatus

RUN_ROLES = {"OWNER", "ADMIN", "MEMBER"}
ACTIVE = ["PENDING", "RUNNING"]


def expire_runs() -> None:
    now = timezone.now()
    AgentRun.objects.filter(state="RUNNING", lease_expires_at__lt=now).update(
        state="FAILED", stage="failed", error_code="interrupted", finished_at=now
    )
    AgentRun.objects.filter(state="PENDING", created_at__lt=now - timedelta(minutes=10)).update(
        state="FAILED", stage="failed", error_code="interrupted", finished_at=now
    )


def runs_today(organization_id: UUID) -> int:
    return (
        AgentRun.objects.filter(
            organization_id=organization_id,
            created_at__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
        ).aggregate(total=Sum("reserved_calls"))["total"]
        or 0
    )


def status(actor: User, organization_id: UUID) -> AgentStatus:
    membership = require_org_member(actor, organization_id)
    config = ModelConfiguration.objects.filter(organization_id=organization_id).first()
    issue = ""
    if config and config.enabled:
        if not config.model:
            issue = "missing_model"
        elif (
            config.provider in {"openai", "anthropic"} or config.base_url in DEFAULT_ENDPOINTS
        ) and not config.encrypted_api_key:
            issue = "missing_key"
        else:
            try:
                endpoint(config.base_url, config.provider)
                validate_model_target(config.base_url, config.model)
            except ValidationError:
                issue = "invalid_endpoint"
            if not issue:
                try:
                    validate_local_limits(config)
                except ValidationError:
                    issue = "invalid_context_window"
    return AgentStatus(
        enabled=bool(config and config.enabled),
        model=config.model if config else "",
        can_manage=membership.role == "OWNER",
        can_run=bool(config and config.enabled and not issue and membership.role in RUN_ROLES),
        runs_today=runs_today(organization_id),
        daily_run_limit=config.daily_run_limit if config else 10,
        configuration_issue=issue,
        max_output_tokens=config.max_output_tokens if config else None,
    )


def list_runs(actor: User, organization_id: UUID, market_id: UUID | None) -> list[AgentRun]:
    require_org_member(actor, organization_id)
    expire_runs()
    query = AgentRun.objects.filter(organization_id=organization_id).exclude(
        kind__in=["PAPER_REVIEW", "ASSIST_TEST"]
    )
    if market_id:
        query = query.filter(market_id=market_id)
    return list(query[:20])


def get_run(actor: User, organization_id: UUID, run_id: UUID) -> AgentRun:
    require_org_member(actor, organization_id)
    expire_runs()
    return get_object_or_404(AgentRun, organization_id=organization_id, pk=run_id)


@transaction.atomic
def enqueue(
    actor: User,
    organization_id: UUID,
    idempotency_key: UUID,
    *,
    market_id: UUID | None = None,
    cutoff: datetime | None = None,
    workflow: Workflow = "single",
    language: Language = "en",
    assistant: Assistant | None = None,
    assistant_graph: dict[str, Any] | None = None,
) -> AgentRun:
    if workflow not in {"single", "team"} or language not in {"zh", "en"}:
        raise ValidationError("Unknown research workflow or language.")
    if not market_id:
        workflow, language = "single", "en"
    calls = len(SKILLS) if workflow == "team" else 1
    kind = "RESEARCH" if market_id else "TEST"
    if assistant is not None:
        from quanthecy_analytics.assistant import AssistantGraph, compile_graph

        if assistant.organization_id != organization_id or market_id is None:
            raise ValidationError("Invalid assistant context.")
        calls = len(compile_graph(AssistantGraph.model_validate(assistant_graph)))
        kind = "ASSIST_TEST"
    roles = RUN_ROLES if market_id else {"OWNER"}
    require_org_role(actor, organization_id, roles)
    Organization.objects.select_for_update().get(pk=organization_id)
    require_org_role(actor, organization_id, roles)
    existing = AgentRun.objects.filter(
        organization_id=organization_id, idempotency_key=idempotency_key
    ).first()
    if existing:
        if (
            existing.market_id != market_id
            or existing.kind != kind
            or existing.workflow != ("assistant" if assistant else workflow)
            or existing.language != language
            or existing.assistant_id != (assistant.id if assistant else None)
            or existing.assistant_graph != assistant_graph
            or (cutoff and existing.cutoff != cutoff)
        ):
            raise ValidationError("This request key was already used for another analysis.")
        return existing
    config = ModelConfiguration.objects.filter(organization_id=organization_id).first()
    if not config or not config.model or (market_id and not config.enabled):
        raise ValidationError("Configure and enable a model before requesting research.")
    endpoint(config.base_url, config.provider)
    validate_model_target(config.base_url, config.model)
    validate_local_limits(config)
    secret = decrypt_key(config)
    if (
        config.provider in {"openai", "anthropic"} or config.base_url in DEFAULT_ENDPOINTS
    ) and not secret:
        raise ValidationError("Save an API key before sending a test or research request.")
    expire_runs()
    if AgentRun.objects.filter(organization_id=organization_id, state__in=ACTIVE).exists():
        raise ValidationError("A request is already queued or running in this workspace.")
    if runs_today(organization_id) + calls > config.daily_run_limit:
        raise ValidationError("The workspace daily request limit has been reached.")
    at = cutoff_time(cutoff)
    if market_id:
        get_object_or_404(Market, pk=market_id, first_observed_at__lte=at)
    from quanthecy_analytics.assistant import VERSION as ASSISTANT_VERSION
    from quanthecy_analytics.intelligence import digest

    return AgentRun.objects.create(
        organization_id=organization_id,
        requested_by=actor,
        market_id=market_id,
        kind=kind,
        idempotency_key=idempotency_key,
        cutoff=at,
        configuration_revision=config.revision,
        provider=config.provider,
        model=config.model,
        workflow="assistant" if assistant else workflow,
        language=language,
        reserved_calls=calls,
        prompt_version=ASSISTANT_VERSION
        if assistant
        else (VERSION if workflow == "team" else "research-v1"),
        assistant=assistant,
        assistant_name=assistant.name if assistant else "",
        assistant_graph=assistant_graph,
        assistant_graph_hash=digest(assistant_graph) if assistant else "",
    )


@transaction.atomic
def cancel_run(actor: User, organization_id: UUID, run_id: UUID) -> AgentRun:
    require_org_role(actor, organization_id, RUN_ROLES)
    Organization.objects.select_for_update().get(pk=organization_id)
    require_org_role(actor, organization_id, RUN_ROLES)
    run = get_object_or_404(AgentRun, organization_id=organization_id, pk=run_id)
    if run.kind == "TEST":
        require_org_role(actor, organization_id, {"OWNER"})
    AgentRun.objects.filter(pk=run.pk, state__in=ACTIVE).update(
        state="CANCELLED", stage="cancelled", finished_at=timezone.now()
    )
    run.refresh_from_db()
    return run


@transaction.atomic
def claim_run() -> AgentRun | None:
    expire_runs()
    run = (
        AgentRun.objects.select_for_update(skip_locked=True)
        .filter(state="PENDING")
        .order_by("created_at", "id")
        .first()
    )
    if run is None:
        return None
    run.state = "RUNNING"
    run.stage = "collecting_context"
    run.lease_token = uuid4()
    run.started_at = timezone.now()
    run.lease_expires_at = timezone.now() + timedelta(minutes=3)
    run.save(update_fields=["state", "stage", "lease_token", "started_at", "lease_expires_at"])
    return run
