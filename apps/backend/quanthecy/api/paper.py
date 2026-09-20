from uuid import UUID

from django.http import HttpRequest
from ninja import Router

from quanthecy.organizations.policies import require_org_member
from quanthecy.paper import services, views
from quanthecy.paper.schemas import (
    CandidateOut,
    CreateInput,
    LabOut,
    OrderDetail,
    PolicyOut,
    ReviewDetail,
    RunningInput,
    UpgradeInput,
)

from .auth import current_user

router = Router(tags=["Paper trading"])


@router.get("/{organization_id}/paper/policy", response=PolicyOut)
def policy(request: HttpRequest, organization_id: UUID) -> PolicyOut:
    require_org_member(current_user(request), organization_id)
    return PolicyOut.model_validate(services.POLICY)


@router.get("/{organization_id}/paper/candidates", response=list[CandidateOut])
def candidates(request: HttpRequest, organization_id: UUID) -> list[dict]:
    return services.candidates(current_user(request), organization_id)


@router.get("/{organization_id}/paper", response=LabOut | None)
def lab(
    request: HttpRequest, organization_id: UUID, experiment_id: UUID | None = None
) -> LabOut | None:
    return views.lab(current_user(request), organization_id, experiment_id)


@router.post("/{organization_id}/paper", response=LabOut)
def create(request: HttpRequest, organization_id: UUID, payload: CreateInput) -> LabOut | None:
    actor = current_user(request)
    services.create_experiment(
        actor,
        organization_id,
        payload.market_ids,
        payload.initial_cash,
        payload.name,
        version=payload.version,
        daily_review_limit=payload.daily_review_limit,
        assistant_version_ids=payload.assistant_version_ids,
    )
    return views.lab(actor, organization_id)


@router.patch("/{organization_id}/paper", response=LabOut)
def running(request: HttpRequest, organization_id: UUID, payload: RunningInput) -> LabOut | None:
    actor = current_user(request)
    services.set_running(actor, organization_id, payload.running, payload.experiment_id)
    return views.lab(actor, organization_id, payload.experiment_id)


@router.get("/{organization_id}/paper/orders/{order_id}", response=OrderDetail)
def order(request: HttpRequest, organization_id: UUID, order_id: UUID) -> OrderDetail:
    return views.order_detail(current_user(request), organization_id, order_id)


@router.post("/{organization_id}/paper/upgrade", response=LabOut)
def upgrade(request: HttpRequest, organization_id: UUID, payload: UpgradeInput) -> LabOut | None:
    actor = current_user(request)
    services.upgrade_experiment(actor, organization_id, payload.daily_review_limit)
    return views.lab(actor, organization_id)


@router.get("/{organization_id}/paper/opportunities/{opportunity_id}", response=ReviewDetail)
def review(request: HttpRequest, organization_id: UUID, opportunity_id: UUID) -> ReviewDetail:
    return views.review_detail(current_user(request), organization_id, opportunity_id)
