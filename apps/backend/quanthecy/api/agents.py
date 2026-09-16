from uuid import UUID

from django.http import HttpRequest
from ninja import Router, Status
from quanthecy_analytics.intelligence import catalog

from quanthecy.agents import configuration, services
from quanthecy.agents.schemas import (
    AgentStatus,
    ConfigurationInput,
    ConfigurationOut,
    RunDetail,
    RunInput,
    RunOut,
    SkillOut,
    TestInput,
)
from quanthecy.organizations.policies import require_org_member

from .auth import current_user

router = Router(tags=["Agent research"])


@router.get("/{organization_id}/agent/skills", response=list[SkillOut])
def skills(request: HttpRequest, organization_id: UUID) -> list[SkillOut]:
    require_org_member(current_user(request), organization_id)
    return [SkillOut(**skill) for skill in catalog()]


@router.get("/{organization_id}/agent/status", response=AgentStatus)
def status(request: HttpRequest, organization_id: UUID) -> AgentStatus:
    return services.status(current_user(request), organization_id)


@router.get("/{organization_id}/agent/configuration", response=ConfigurationOut)
def settings(request: HttpRequest, organization_id: UUID) -> ConfigurationOut:
    return configuration.get_configuration(current_user(request), organization_id)


@router.put("/{organization_id}/agent/configuration", response=ConfigurationOut)
def save(
    request: HttpRequest, organization_id: UUID, payload: ConfigurationInput
) -> ConfigurationOut:
    return configuration.save_configuration(current_user(request), organization_id, payload)


@router.post("/{organization_id}/agent/test", response={202: RunOut})
def test(request: HttpRequest, organization_id: UUID, payload: TestInput) -> Status[RunOut]:
    return Status(
        202,
        RunOut.from_orm(
            services.enqueue(current_user(request), organization_id, payload.idempotency_key)
        ),
    )


@router.post("/{organization_id}/agent/markets/{market_id}/runs", response={202: RunOut})
def create(
    request: HttpRequest, organization_id: UUID, market_id: UUID, payload: RunInput
) -> Status[RunOut]:
    return Status(
        202,
        RunOut.from_orm(
            services.enqueue(
                current_user(request),
                organization_id,
                payload.idempotency_key,
                market_id=market_id,
                cutoff=payload.cutoff,
                workflow=payload.workflow,
                language=payload.language,
            )
        ),
    )


@router.get("/{organization_id}/agent/runs", response=list[RunOut])
def runs(
    request: HttpRequest, organization_id: UUID, market_id: UUID | None = None
) -> list[RunOut]:
    return [
        RunOut.from_orm(run)
        for run in services.list_runs(current_user(request), organization_id, market_id)
    ]


@router.get("/{organization_id}/agent/runs/{run_id}", response=RunDetail)
def detail(request: HttpRequest, organization_id: UUID, run_id: UUID) -> RunDetail:
    return RunDetail.from_orm(services.get_run(current_user(request), organization_id, run_id))


@router.post("/{organization_id}/agent/runs/{run_id}/cancel", response=RunOut)
def cancel(request: HttpRequest, organization_id: UUID, run_id: UUID) -> RunOut:
    return RunOut.from_orm(services.cancel_run(current_user(request), organization_id, run_id))
