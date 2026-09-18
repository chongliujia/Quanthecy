from uuid import UUID

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from ninja import Router, Status
from quanthecy_analytics.assistant import AssistantGraph, default_graph

from quanthecy.agents import assistants
from quanthecy.agents.assistant_schemas import (
    AssistantCreate,
    AssistantOut,
    AssistantRunSummary,
    AssistantSave,
    AssistantTrial,
    GraphValidation,
    RevisionInput,
    VersionOut,
)
from quanthecy.agents.models import AgentRun
from quanthecy.agents.schemas import RunOut
from quanthecy.agents.services import expire_runs
from quanthecy.organizations.policies import require_org_member

from .auth import current_user

router = Router(tags=["Paper assistants"])


@router.get("/{organization_id}/assistants/template", response=AssistantGraph)
def template(request: HttpRequest, organization_id: UUID) -> AssistantGraph:
    require_org_member(current_user(request), organization_id)
    return default_graph()


@router.post("/{organization_id}/assistants/validate", response=GraphValidation)
def validate(
    request: HttpRequest, organization_id: UUID, payload: AssistantGraph
) -> GraphValidation:
    require_org_member(current_user(request), organization_id)
    try:
        assistants.validate(payload)
    except ValidationError as exc:
        return GraphValidation(valid=False, errors=exc.messages, model_calls=len(payload.nodes))
    return GraphValidation(valid=True, errors=[], model_calls=len(payload.nodes))


@router.get("/{organization_id}/assistants/runs", response=list[AssistantRunSummary])
def runs(request: HttpRequest, organization_id: UUID) -> list[AssistantRunSummary]:
    require_org_member(current_user(request), organization_id)
    expire_runs()
    return [
        AssistantRunSummary.from_orm(run)
        for run in AgentRun.objects.filter(
            organization_id=organization_id,
            workflow="assistant",
        ).defer("steps", "context", "report", "assistant_graph")[:30]
    ]


@router.get("/{organization_id}/assistants", response=list[AssistantOut])
def listing(request: HttpRequest, organization_id: UUID) -> list[AssistantOut]:
    return assistants.list_assistants(current_user(request), organization_id)


@router.post("/{organization_id}/assistants", response=AssistantOut)
def create(request: HttpRequest, organization_id: UUID, payload: AssistantCreate) -> AssistantOut:
    return assistants.serialize(
        assistants.create(
            current_user(request),
            organization_id,
            payload.name,
            payload.source_id,
        )
    )


@router.put("/{organization_id}/assistants/{assistant_id}", response=AssistantOut)
def save(
    request: HttpRequest, organization_id: UUID, assistant_id: UUID, payload: AssistantSave
) -> AssistantOut:
    return assistants.serialize(
        assistants.save(current_user(request), organization_id, assistant_id, payload)
    )


@router.post("/{organization_id}/assistants/{assistant_id}/publish", response=VersionOut)
def publish(
    request: HttpRequest, organization_id: UUID, assistant_id: UUID, payload: RevisionInput
) -> VersionOut:
    return VersionOut.from_orm(
        assistants.publish(current_user(request), organization_id, assistant_id, payload.revision)
    )


@router.post("/{organization_id}/assistants/{assistant_id}/trial", response={202: RunOut})
def trial(
    request: HttpRequest, organization_id: UUID, assistant_id: UUID, payload: AssistantTrial
) -> Status[RunOut]:
    return Status(
        202,
        RunOut.from_orm(
            assistants.trial(
                current_user(request),
                organization_id,
                assistant_id,
                payload.revision,
                payload.market_id,
                payload.idempotency_key,
            )
        ),
    )
