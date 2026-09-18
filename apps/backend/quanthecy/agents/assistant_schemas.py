from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import Field
from quanthecy_analytics.assistant import AssistantGraph

from quanthecy.api.schemas import InputSchema


class AssistantCreate(InputSchema):
    name: str = Field(min_length=1, max_length=120)
    source_id: UUID | None = None


class AssistantSave(InputSchema):
    name: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    graph: AssistantGraph


class RevisionInput(InputSchema):
    revision: int = Field(ge=1)


class AssistantTrial(RevisionInput):
    market_id: UUID
    idempotency_key: UUID


class VersionOut(Schema):
    id: UUID
    assistant_id: UUID
    number: int
    name: str
    graph: AssistantGraph
    graph_hash: str
    runtime_version: str
    created_at: datetime


class AssistantOut(Schema):
    id: UUID
    name: str
    revision: int
    is_default: bool
    draft: AssistantGraph
    versions: list[VersionOut]
    updated_at: datetime


class GraphValidation(Schema):
    valid: bool
    errors: list[str]
    model_calls: int


class AssistantRunSummary(Schema):
    id: UUID
    kind: str
    state: str
    stage: str
    model: str
    assistant_id: UUID | None
    assistant_version_id: UUID | None
    assistant_name: str
    reserved_calls: int
    usage: dict[str, int]
    error_code: str
    created_at: datetime
    finished_at: datetime | None
