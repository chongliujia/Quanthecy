"""LangGraph node adapter for the existing leased worker and provider boundary."""

import json
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import timedelta
from threading import Event
from typing import Any, cast

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.http import Http404
from django.utils import timezone
from pydantic import ValidationError as SchemaError
from quanthecy_analytics.assistant import (
    VERSION,
    AssistantGraph,
    AssistantState,
    GraphNode,
    build_workflow,
    compile_graph,
    node_input,
    node_instructions,
    node_skill,
)
from quanthecy_analytics.intelligence import Language, digest, validate_stage
from quanthecy_analytics.paper_review import validate_review
from quanthecy_analytics.report_validation import ListGrouping, validation_issues

from .models import AgentRun
from .provider import Connection, ProviderFailure


def execute(
    run: AgentRun,
    context: dict[str, Any],
    stopped: Event,
    complete: Callable[[Connection, str, str, Event], tuple[str, dict[str, int]]],
) -> None:
    from .worker import connection_for, live_run, publish

    graph = AssistantGraph.model_validate(run.assistant_graph)
    if (
        run.prompt_version != VERSION
        or digest(run.assistant_graph) != run.assistant_graph_hash
        or run.reserved_calls != len(compile_graph(graph))
        or run.assistant is None
        or run.assistant.organization_id != run.organization_id
    ):
        raise ProviderFailure("configuration_changed")
    if run.assistant_version is not None and (
        run.assistant_version.assistant_id != run.assistant_id
        or run.assistant_version.graph_hash != run.assistant_graph_hash
        or run.assistant_version.runtime_version != VERSION
    ):
        raise ProviderFailure("configuration_changed")
    steps: list[dict[str, Any]] = []
    usage: dict[str, int] = {}

    def node(node: GraphNode, state: AssistantState) -> dict[str, Any]:
        # LangGraph executes synchronous nodes in its executor. Connections are
        # local to that thread and never shared with the worker's DB connection.
        close_old_connections()
        phase = "context"
        step: dict[str, Any] | None = None
        try:
            if stopped.is_set() or not live_run(run).exists():
                raise PermissionDenied("Run cancelled")
            connection = connection_for(run)
            if node.max_output_tokens is not None:
                connection = replace(
                    connection,
                    max_output_tokens=min(connection.max_output_tokens, node.max_output_tokens),
                )
            packet = node_input(state["context"], graph, node, state["outputs"])
            system = node_instructions(graph, node, cast(Language, run.language))
            skill = node_skill(graph, node)
            step = {
                "id": node.id,
                "name": node.label,
                "skill_version": VERSION,
                "skill": asdict(skill),
                "state": "RUNNING",
                "started_at": timezone.now().isoformat(),
                "finished_at": None,
                "output": None,
                "usage": {},
                "model_settings": {
                    "provider": connection.provider,
                    "model": connection.model,
                    "configuration_revision": run.configuration_revision,
                    "max_output_tokens": connection.max_output_tokens,
                },
                "error_code": "",
                "validation_errors": [],
                "format_adjustments": [],
                "input_packet": packet,
                "input_manifest": {
                    "cutoff": context["cutoff"],
                    "context_sha256": digest(packet),
                    "reference_ids": [r["id"] for r in packet["context"]["references"]],
                    "omitted_reference_ids": packet["context"]["omitted_reference_ids"],
                    "reference_bytes": packet["context"]["reference_bytes"],
                    "dependencies": list(skill.dependencies),
                    "system_sha256": digest(system),
                },
            }
            steps.append(step)
            usage["provider_calls"] = usage.get("provider_calls", 0) + 1
            if usage["provider_calls"] > run.reserved_calls:
                raise PermissionDenied("Reserved calls exhausted")
            if not live_run(run).update(
                steps=steps,
                stage=node.id,
                usage=usage,
                lease_expires_at=timezone.now() + timedelta(seconds=connection.lease_seconds),
            ):
                raise PermissionDenied("Run cancelled")
            phase = "provider"
            raw, tokens = complete(
                connection, system, json.dumps(packet, ensure_ascii=False), stopped
            )
            for key, count in tokens.items():
                usage[key] = usage.get(key, 0) + count
            step["usage"] = tokens
            if stopped.is_set() or not live_run(run).exists():
                raise PermissionDenied("Run cancelled")
            connection_for(run)
            phase = "validation"
            adjustments: list[ListGrouping] = []
            output = (
                validate_review(raw, packet["context"]).model_dump(mode="json")
                if node.kind == "review"
                else validate_stage(raw, skill, packet["context"], adjustments=adjustments)
            )
            step.update(
                state="SUCCEEDED",
                output=output,
                finished_at=timezone.now().isoformat(),
                format_adjustments=[item.model_dump() for item in adjustments],
            )
            if not live_run(run).update(steps=steps, usage=usage):
                raise PermissionDenied("Run cancelled")
            return output
        except Exception as exc:
            cancelled = isinstance(exc, (PermissionDenied, Http404))
            code = (
                "configuration_changed"
                if cancelled
                else (
                    str(exc)
                    if isinstance(exc, ProviderFailure)
                    else (
                        "invalid_report"
                        if phase == "validation"
                        else "provider_failed"
                        if phase == "provider"
                        else "context_unavailable"
                    )
                )
            )
            issues = (
                validation_issues(exc)
                if phase == "validation"
                and isinstance(exc, (SchemaError, ValueError, ValidationError))
                else []
            )
            if step is not None:
                step.update(
                    state="CANCELLED" if cancelled else "FAILED",
                    error_code=code,
                    validation_errors=issues,
                    finished_at=timezone.now().isoformat(),
                )
            live_run(run).update(
                state="CANCELLED" if cancelled else "FAILED",
                stage="cancelled" if cancelled else "failed",
                steps=steps,
                usage=usage,
                error_code=code,
                validation_errors=issues,
                finished_at=timezone.now(),
            )
            # A pause/cancel may already have ended the lease while a provider
            # was returning. Preserve attempted usage and mark its node terminal
            # without changing the existing cancellation reason or publishing.
            AgentRun.objects.filter(
                pk=run.pk,
                lease_token=run.lease_token,
                state__in=["CANCELLED", "FAILED"],
            ).update(steps=steps, usage=usage)
            raise
        finally:
            close_old_connections()

    workflow = build_workflow(graph, node)
    result = workflow.invoke(
        {"context": context, "outputs": {}, "report": None},
        # Independent branches share no peer findings. Bounded execution avoids
        # request bursts and serializes the lease/audit updates for this run.
        config={"max_concurrency": 1, "recursion_limit": 12, "callbacks": []},
    )
    if stopped.is_set():
        raise PermissionDenied("Run cancelled")
    publish(run, result["report"], usage)
