"""Organization-scoped drafts, immutable releases and explicit preview admission."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from quanthecy_analytics.assistant import VERSION, AssistantGraph, compile_graph, default_graph
from quanthecy_analytics.intelligence import digest

from quanthecy.accounts.models import User
from quanthecy.organizations.models import Organization
from quanthecy.organizations.policies import require_org_member, require_org_role

from .assistant_schemas import AssistantOut, AssistantSave, VersionOut
from .models import AgentRun, Assistant, AssistantVersion
from .services import RUN_ROLES, enqueue


def validate(graph: AssistantGraph) -> None:
    try:
        compile_graph(graph)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def serialize(assistant: Assistant) -> AssistantOut:
    return AssistantOut(
        id=assistant.id,
        name=assistant.name,
        revision=assistant.revision,
        is_default=assistant.is_default,
        draft=AssistantGraph.model_validate(assistant.draft),
        versions=[VersionOut.from_orm(v) for v in assistant.versions.order_by("-number")[:20]],
        updated_at=assistant.updated_at,
    )


def list_assistants(actor: User, organization_id: UUID) -> list[AssistantOut]:
    require_org_member(actor, organization_id)
    return [
        serialize(a)
        for a in Assistant.objects.filter(
            organization_id=organization_id,
        ).order_by("-is_default", "-updated_at")
    ]


@transaction.atomic
def create(actor: User, organization_id: UUID, name: str, source_id: UUID | None) -> Assistant:
    require_org_role(actor, organization_id, RUN_ROLES)
    Organization.objects.select_for_update().get(pk=organization_id)
    require_org_role(actor, organization_id, RUN_ROLES)
    if not name.strip():
        raise ValidationError("Give the assistant a name.")
    if Assistant.objects.filter(organization_id=organization_id).count() >= 30:
        raise ValidationError("A workspace can keep up to 30 assistants.")
    source = (
        get_object_or_404(Assistant, organization_id=organization_id, id=source_id)
        if source_id
        else None
    )
    return Assistant.objects.create(
        organization_id=organization_id,
        created_by=actor,
        name=name.strip(),
        draft=source.draft if source else default_graph().model_dump(mode="json"),
    )


def locked(actor: User, organization_id: UUID, assistant_id: UUID, revision: int) -> Assistant:
    require_org_role(actor, organization_id, RUN_ROLES)
    Organization.objects.select_for_update().get(pk=organization_id)
    require_org_role(actor, organization_id, RUN_ROLES)
    assistant = get_object_or_404(
        Assistant.objects.select_for_update(),
        organization_id=organization_id,
        id=assistant_id,
    )
    if assistant.revision != revision:
        raise ValidationError("This draft changed in another session. Reload it before continuing.")
    return assistant


@transaction.atomic
def save(
    actor: User, organization_id: UUID, assistant_id: UUID, payload: AssistantSave
) -> Assistant:
    assistant = locked(actor, organization_id, assistant_id, payload.revision)
    if assistant.is_default:
        raise ValidationError("Copy the default assistant before editing it.")
    if not payload.name.strip():
        raise ValidationError("Give the assistant a name.")
    assistant.name = payload.name.strip()
    assistant.draft = payload.graph.model_dump(mode="json")
    assistant.revision += 1
    assistant.save(update_fields=["name", "draft", "revision", "updated_at"])
    return assistant


def release(actor: User, assistant: Assistant) -> AssistantVersion:
    graph = AssistantGraph.model_validate(assistant.draft)
    validate(graph)
    graph_hash = digest(graph.model_dump(mode="json"))
    previous = assistant.versions.order_by("-number").first()
    if previous and previous.graph_hash == graph_hash and previous.name == assistant.name:
        return previous
    if previous and previous.number >= 100:
        raise ValidationError("This assistant has reached its 100-version limit.")
    return AssistantVersion.objects.create(
        assistant=assistant,
        number=previous.number + 1 if previous else 1,
        name=assistant.name,
        graph=graph.model_dump(mode="json"),
        graph_hash=graph_hash,
        runtime_version=VERSION,
        created_by=actor,
    )


@transaction.atomic
def publish(
    actor: User, organization_id: UUID, assistant_id: UUID, revision: int
) -> AssistantVersion:
    return release(actor, locked(actor, organization_id, assistant_id, revision))


@transaction.atomic
def default_version(actor: User, organization_id: UUID) -> AssistantVersion:
    require_org_role(actor, organization_id, RUN_ROLES)
    Organization.objects.select_for_update().get(pk=organization_id)
    assistant, _ = Assistant.objects.get_or_create(
        organization_id=organization_id,
        is_default=True,
        defaults={
            "name": "Default research team",
            "created_by": actor,
            "draft": default_graph().model_dump(mode="json"),
        },
    )
    return release(actor, assistant)


@transaction.atomic
def trial(
    actor: User,
    organization_id: UUID,
    assistant_id: UUID,
    revision: int,
    market_id: UUID,
    idempotency_key: UUID,
) -> AgentRun:
    assistant = locked(actor, organization_id, assistant_id, revision)
    graph = AssistantGraph.model_validate(assistant.draft)
    validate(graph)
    return enqueue(
        actor,
        organization_id,
        idempotency_key,
        market_id=market_id,
        language="zh",
        assistant=assistant,
        assistant_graph=graph.model_dump(mode="json"),
    )
