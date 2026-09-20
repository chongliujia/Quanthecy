from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field, SecretStr
from quanthecy_analytics.agent import ResearchReport
from quanthecy_analytics.intelligence import (
    IntelligenceReport,
    Language,
    RiskReviewOutput,
    SpecialistOutput,
    Workflow,
)
from quanthecy_analytics.paper_review import EntryReview
from quanthecy_analytics.report_validation import ListGrouping, ValidationIssue

from quanthecy.api.schemas import InputSchema


class ConfigurationInput(InputSchema):
    revision: int = Field(ge=0)
    provider: Literal["openai", "openai_compatible", "anthropic", "local"]
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(max_length=160)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    enabled: bool
    daily_run_limit: int = Field(ge=1, le=100)
    max_output_tokens: int = Field(ge=256, le=65536)
    context_window_tokens: int | None = Field(default=None, ge=512, le=1048576)
    enable_thinking: bool = False


class ConnectionOut(Schema):
    id: UUID
    provider: str
    base_url: str
    model: str
    has_api_key: bool
    max_output_tokens: int
    context_window_tokens: int | None
    enable_thinking: bool


class ConfigurationOut(Schema):
    revision: int
    provider: str
    base_url: str
    model: str
    has_api_key: bool
    encryption_available: bool
    enabled: bool
    daily_run_limit: int
    max_output_tokens: int
    context_window_tokens: int | None
    enable_thinking: bool
    allowed_endpoints: list[str]
    max_output_tokens_limit: int = 65536
    connections: list[ConnectionOut] = Field(default_factory=list)


class AgentStatus(Schema):
    enabled: bool
    model: str
    can_manage: bool
    can_run: bool
    runs_today: int
    daily_run_limit: int
    configuration_issue: str = ""
    max_output_tokens: int | None = None


class RunInput(InputSchema):
    idempotency_key: UUID
    cutoff: datetime | None = None
    workflow: Workflow = "single"
    language: Language = "en"


class TestInput(InputSchema):
    idempotency_key: UUID


class SkillOut(Schema):
    id: str
    name: str
    responsibility: str
    reference_kinds: list[str]
    dependencies: list[str]
    checklist: list[str]
    version: str


class StageManifest(Schema):
    cutoff: datetime
    context_sha256: str
    reference_ids: list[str]
    omitted_reference_ids: list[str]
    reference_bytes: int
    dependencies: list[str]
    system_sha256: str


class StageModelSettings(Schema):
    provider: str
    model: str
    configuration_revision: int
    max_output_tokens: int


class StageOut(Schema):
    id: str
    name: str
    skill_version: str
    skill: SkillOut | None = None
    state: str
    started_at: datetime
    finished_at: datetime | None
    output: RiskReviewOutput | SpecialistOutput | IntelligenceReport | EntryReview | None
    input_packet: dict[str, Any] | None = None
    model_settings: StageModelSettings | None = None
    usage: dict[str, int]
    error_code: str
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    format_adjustments: list[ListGrouping] = Field(default_factory=list)
    input_manifest: StageManifest


class RunOut(Schema):
    id: UUID
    market_id: UUID | None
    kind: str
    state: str
    stage: str
    cutoff: datetime
    configuration_revision: int
    model: str
    prompt_version: str
    workflow: str
    language: str
    reserved_calls: int
    assistant_id: UUID | None = None
    assistant_version_id: UUID | None = None
    assistant_graph_hash: str = ""
    assistant_name: str = ""
    steps: list[StageOut]
    report: IntelligenceReport | ResearchReport | EntryReview | None
    usage: dict[str, Any]
    error_code: str
    validation_errors: list[ValidationIssue]
    created_at: datetime
    finished_at: datetime | None


class RunDetail(RunOut):
    context: dict[str, Any]
    assistant_graph: dict[str, Any] | None = None
