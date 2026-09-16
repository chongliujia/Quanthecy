import json
import multiprocessing
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta
from threading import Event
from typing import Any, cast

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from pydantic import ValidationError as SchemaError
from quanthecy_analytics.agent import PROMPT, ResearchReport, validate_report
from quanthecy_analytics.intelligence import (
    SKILLS,
    VERSION,
    Language,
    digest,
    instructions,
    stage_input,
    validate_stage,
)
from quanthecy_analytics.report_validation import ListGrouping, validation_issues

from quanthecy.organizations.models import Organization
from quanthecy.organizations.policies import require_org_role

from .configuration import decrypt_key, endpoint
from .context import build_context
from .models import AgentRun, ModelConfiguration
from .provider import ERROR_CODES, Connection, ProviderFailure, child_complete
from .services import RUN_ROLES, claim_run


def bounded_complete(
    connection: Connection, system: str, prompt: str, stopped: Event
) -> tuple[str, dict[str, int]]:
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    child = context.Process(target=child_complete, args=(writer, connection, system, prompt))
    child.start()
    writer.close()
    deadline = time.monotonic() + connection.deadline_seconds
    try:
        while time.monotonic() < deadline and not stopped.is_set():
            if reader.poll(0.2):
                kind, value = reader.recv()
                if kind == "ok":
                    text, usage = value
                    return str(text), dict(usage)
                raise ProviderFailure(
                    value if isinstance(value, str) and value in ERROR_CODES else "provider_failed"
                )
            if not child.is_alive():
                raise ProviderFailure("provider_failed")
        raise ProviderFailure("provider_timeout")
    except EOFError:
        raise ProviderFailure("provider_failed") from None
    finally:
        reader.close()
        if child.is_alive():
            child.terminate()
        child.join(timeout=2)
        if child.is_alive():
            child.kill()
            child.join(timeout=2)


def live_run(run: AgentRun) -> Any:
    return AgentRun.objects.filter(
        pk=run.pk, state="RUNNING", lease_token=run.lease_token, lease_expires_at__gt=timezone.now()
    )


def connection_for(run: AgentRun) -> Connection:
    run.requested_by.refresh_from_db()
    config = ModelConfiguration.objects.get(organization_id=run.organization_id)
    if config.revision != run.configuration_revision or (
        run.kind == "RESEARCH" and not config.enabled
    ):
        raise ProviderFailure("configuration_changed")
    require_org_role(
        run.requested_by, run.organization_id, RUN_ROLES if run.kind == "RESEARCH" else {"OWNER"}
    )
    return Connection(
        config.provider,
        endpoint(config.base_url, config.provider),
        config.model,
        decrypt_key(config),
        min(config.max_output_tokens, 256) if run.kind == "TEST" else config.max_output_tokens,
    )


@transaction.atomic
def publish(run: AgentRun, report: dict[str, Any] | None, usage: dict[str, int]) -> None:
    Organization.objects.select_for_update().get(pk=run.organization_id)
    connection_for(run)
    live_run(run).update(
        state="SUCCEEDED", stage="completed", report=report, usage=usage, finished_at=timezone.now()
    )


def process_one(
    stopped: Event,
    complete: Callable[
        [Connection, str, str, Event], tuple[str, dict[str, int]]
    ] = bounded_complete,
) -> bool:
    run = claim_run()
    if run is None:
        return False
    phase = "context"
    usage: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    try:
        connection = connection_for(run)
        if run.kind == "TEST":
            context: dict[str, Any] = {}
            prompt = 'Return the JSON object {"ok": true}.'
            system = "Verify this connection by returning the requested JSON."
        else:
            assert run.market_id is not None
            context = build_context(run.market_id, run.cutoff)
            prompt = json.dumps(
                {
                    "context": {k: v for k, v in context.items() if k != "observations"},
                    "report_schema": ResearchReport.model_json_schema(),
                }
            )
            system = PROMPT
            system += "\nWrite narrative fields in " + (
                "Simplified Chinese." if run.language == "zh" else "English."
            )
        if not live_run(run).update(context=context, stage="analyzing") or stopped.is_set():
            return True
        if run.workflow == "team":
            if run.prompt_version != VERSION or run.reserved_calls != len(SKILLS):
                raise ProviderFailure("configuration_changed")
            outputs: dict[str, dict[str, Any]] = {}
            report = None
            for skill in SKILLS:
                phase = "context"
                if stopped.is_set() or not live_run(run).exists():
                    return True
                connection = connection_for(run)
                packet = stage_input(context, skill, outputs)
                system = instructions(skill, cast(Language, run.language))
                step: dict[str, Any] = {
                    "id": skill.id,
                    "name": skill.name,
                    "skill_version": skill.version,
                    "skill": asdict(skill),
                    "state": "RUNNING",
                    "started_at": timezone.now().isoformat(),
                    "finished_at": None,
                    "output": None,
                    "usage": {},
                    "error_code": "",
                    "validation_errors": [],
                    "format_adjustments": [],
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
                if not live_run(run).update(
                    steps=steps,
                    stage=skill.id,
                    usage=usage,
                    lease_expires_at=timezone.now() + timedelta(seconds=connection.lease_seconds),
                ):
                    return True
                phase = "provider"
                raw, tokens = complete(
                    connection, system, json.dumps(packet, ensure_ascii=False), stopped
                )
                for key, count in tokens.items():
                    usage[key] = usage.get(key, 0) + count
                step["usage"] = tokens
                AgentRun.objects.filter(pk=run.pk, lease_token=run.lease_token).update(usage=usage)
                if stopped.is_set() or not live_run(run).exists():
                    return True
                connection_for(run)
                phase = "validation"
                adjustments: list[ListGrouping] = []
                output = validate_stage(raw, skill, packet["context"], adjustments=adjustments)
                step.update(
                    state="SUCCEEDED",
                    output=output,
                    finished_at=timezone.now().isoformat(),
                    format_adjustments=[item.model_dump() for item in adjustments],
                )
                if not live_run(run).update(steps=steps, usage=usage):
                    return True
                if skill.id == "synthesis":
                    report = output
                else:
                    outputs[skill.id] = output
            publish(run, report, usage)
            return True
        # Recheck the settings/role immediately before the only external request.
        connection = connection_for(run)
        if not live_run(run).update(
            lease_expires_at=timezone.now() + timedelta(seconds=connection.lease_seconds)
        ):
            return True
        phase = "provider"
        raw, usage = complete(connection, system, prompt, stopped)
        AgentRun.objects.filter(pk=run.pk, lease_token=run.lease_token).update(usage=usage)
        phase = "validation"
        if not live_run(run).update(stage="validating", usage=usage):
            return True
        if run.kind == "TEST":
            if json.loads(raw) != {"ok": True}:
                raise ValueError("Invalid test response")
            report = None
        else:
            report = validate_report(raw, context).model_dump(mode="json")
        publish(run, report, usage)
    except ProviderFailure as exc:
        live_run(run).update(
            state="FAILED",
            stage="failed",
            error_code=str(exc),
            usage=usage,
            finished_at=timezone.now(),
        )
    except (PermissionDenied, Http404):
        live_run(run).update(
            state="CANCELLED",
            stage="cancelled",
            error_code="configuration_changed",
            finished_at=timezone.now(),
        )
    except (SchemaError, ValueError, ValidationError) as exc:
        code = "invalid_report" if phase == "validation" else "context_unavailable"
        live_run(run).update(
            state="FAILED",
            stage="failed",
            error_code=code,
            usage=usage,
            validation_errors=validation_issues(exc) if phase == "validation" else [],
            finished_at=timezone.now(),
        )
    except Exception:
        # Provider and context exceptions can contain secrets or raw source material.
        code = "provider_failed" if phase == "provider" else "context_unavailable"
        live_run(run).update(
            state="FAILED", stage="failed", error_code=code, usage=usage, finished_at=timezone.now()
        )
    finally:
        if steps and steps[-1]["state"] == "RUNNING":
            current = AgentRun.objects.get(pk=run.pk)
            if current.lease_token == run.lease_token and current.state in {"FAILED", "CANCELLED"}:
                steps[-1].update(
                    state=current.state,
                    error_code=current.error_code,
                    validation_errors=current.validation_errors,
                    finished_at=timezone.now().isoformat(),
                )
                AgentRun.objects.filter(pk=run.pk, lease_token=run.lease_token).update(steps=steps)
    return True
