import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.agents.configuration import decrypt_key, save_configuration
from quanthecy.agents.context import build_context
from quanthecy.agents.models import AgentRun, ModelConfiguration
from quanthecy.agents.provider import Connection, NoRedirect, ProviderFailure, complete
from quanthecy.agents.schemas import ConfigurationInput
from quanthecy.agents.services import cancel_run, claim_run, enqueue, expire_runs
from quanthecy.agents.worker import process_one
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import Market
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.services import create_organization
from quanthecy.research.feeds import FeedEntry
from quanthecy.research.models import EvidenceLink, EvidenceSource
from quanthecy.research.news import initialize_sources, persist_entry
from quanthecy_analytics.agent import validate_report
from quanthecy_analytics.signals import analyze

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def agent_settings(settings):
    settings.AGENT_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.AGENT_ALLOWED_ENDPOINTS = ["https://api.openai.com/v1", "https://model.example/v1"]


@pytest.fixture
def actor():
    return User.objects.create_user("agent-owner@example.com", "test-password")


@pytest.fixture
def organization(actor):
    return create_organization(owner=actor, name="Research desk")


@pytest.fixture
def client(actor):
    value = Client()
    value.force_login(actor)
    return value


@pytest.fixture
def rows():
    return json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )


@pytest.fixture
def market(rows):
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    return Market.objects.get()


def payload(**changes):
    return dict(
        revision=0,
        provider="openai_compatible",
        base_url="https://model.example/v1",
        model="test-model",
        enabled=False,
        daily_run_limit=10,
        max_output_tokens=2000,
        **changes,
    )


@pytest.fixture
def configured(actor, organization):
    values = payload()
    values.update(enabled=True, api_key="secret-for-testing-only")
    save_configuration(actor, organization.id, ConfigurationInput(**values))
    return ModelConfiguration.objects.get(organization=organization)


def report(reference="market"):
    return {
        "action": "WATCH",
        "confidence": 0.6,
        "thesis": {
            "kind": "HYPOTHESIS",
            "text": "This market warrants further investigation.",
            "references": [reference],
        },
        "claims": [],
        "counter_evidence": [],
        "key_signals": [],
        "risk_flags": ["No causal conclusion is supported."],
        "follow_up": ["Monitor the next official announcement."],
    }


def team_output(final=False, reference="market"):
    thesis = report(reference)["thesis"]
    if not final:
        return {
            "summary": thesis,
            "findings": [],
            "challenges": [],
            "limitations": ["Limited evidence."],
            "watch_for": [],
        }
    return {
        **report(),
        "disagreements": [],
        "forecast": {
            "status": "ABSTAIN",
            "target": "YES_AT_CONTRACT_RESOLUTION",
            "probability": None,
            "lower": None,
            "upper": None,
            "rationale": thesis,
            "assumptions": [],
            "invalidation_triggers": [],
            "calibration": "UNCALIBRATED",
        },
    }


def test_team_workflow_persists_stages_scoped_inputs_and_abstention(
    client, actor, organization, configured, market, rows
):
    from quanthecy.agents.services import runs_today

    cutoff = datetime.fromisoformat(rows[-1]["recorded_at"])
    run = enqueue(
        actor,
        organization.id,
        uuid4(),
        market_id=market.id,
        cutoff=cutoff,
        workflow="team",
        language="zh",
    )
    repo = Mock(history=Mock(return_value=rows))
    packets = []

    def provider(connection, system, prompt, stopped):
        assert "Simplified Chinese" in system
        packets.append(json.loads(prompt))
        return json.dumps(team_output(final=len(packets) == 5)), {"total_tokens": 10}

    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        process_one(Event(), provider)
    run.refresh_from_db()
    assert run.state == "SUCCEEDED", run.error_code
    assert run.usage == {"provider_calls": 5, "total_tokens": 50}
    assert len(run.steps) == 5 and all(s["state"] == "SUCCEEDED" for s in run.steps)
    assert run.report["forecast"]["probability"] is None
    assert run.context["manifest"]["observation_count"] == len(rows)
    assert len(run.steps[0]["skill"]["checklist"]) == 4
    assert runs_today(organization.id) == 5
    assert all(not p["peer_findings"] for p in packets[:3])
    assert len(packets[3]["peer_findings"]) == 3
    assert len(packets[4]["peer_findings"]) == 4
    assert all("observations" not in p["context"] for p in packets)
    path = f"/api/v1/organizations/{organization.id}/agent/runs/{run.id}"
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["report"]["forecast"]["status"] == "ABSTAIN"
    assert response.json()["steps"][0]["output"]["summary"]


@pytest.mark.parametrize("interruption", ["bad_citation", "provider", "cancel", "settings", "role"])
def test_team_stops_between_stages_without_publishing_partial_report(
    actor, organization, configured, market, rows, interruption
):
    run = enqueue(
        actor,
        organization.id,
        uuid4(),
        market_id=market.id,
        cutoff=datetime.fromisoformat(rows[-1]["recorded_at"]),
        workflow="team",
    )
    repo = Mock(history=Mock(return_value=rows))
    calls = []

    def provider(*args):
        calls.append(1)
        if len(calls) == 2:
            if interruption == "bad_citation":
                return json.dumps(team_output(reference="metric:probability_change_15m")), {}
            if interruption == "provider":
                raise ProviderFailure("provider_rate_limit")
            if interruption == "cancel":
                cancel_run(actor, organization.id, run.id)
            if interruption == "settings":
                values = payload()
                values.update(revision=1, model="changed", enabled=True)
                save_configuration(actor, organization.id, ConfigurationInput(**values))
            if interruption == "role":
                OrganizationMembership.objects.filter(user=actor, organization=organization).update(
                    role="VIEWER"
                )
        return json.dumps(team_output()), {"total_tokens": 3}

    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        process_one(Event(), provider)
    run.refresh_from_db()
    assert len(calls) == 2
    assert run.state in {"FAILED", "CANCELLED"} and run.report is None
    assert run.steps[0]["state"] == "SUCCEEDED"
    assert run.steps[1]["state"] == run.state and run.steps[1]["output"] is None
    assert run.usage["provider_calls"] == 2


def test_team_budget_idempotency_and_skill_tenant_boundary(
    client, actor, organization, configured, market
):
    configured.daily_run_limit = 4
    configured.save()
    with pytest.raises(ValidationError, match="daily request limit"):
        enqueue(actor, organization.id, uuid4(), market_id=market.id, workflow="team")
    assert not AgentRun.objects.exists()
    configured.daily_run_limit = 5
    configured.save()
    key = uuid4()
    run = enqueue(actor, organization.id, key, market_id=market.id, workflow="team")
    assert enqueue(actor, organization.id, key, market_id=market.id, workflow="team").id == run.id
    with pytest.raises(ValidationError, match="already used"):
        enqueue(actor, organization.id, key, market_id=market.id, workflow="single")
    cancel_run(actor, organization.id, run.id)
    with pytest.raises(ValidationError, match="daily request limit"):
        enqueue(actor, organization.id, uuid4())
    path = f"/api/v1/organizations/{organization.id}/agent/skills"
    assert len(client.get(path).json()) == 5
    outsider = User.objects.create_superuser("other-reviewer@example.com", "test-password")
    client.force_login(outsider)
    assert client.get(path).status_code == 404


def test_configuration_saves_encrypted_and_never_calls_provider(client, actor, organization):
    path = f"/api/v1/organizations/{organization.id}/agent/configuration"
    assert client.get(path).json()["enabled"] is False
    with patch("quanthecy.agents.provider.complete") as provider:
        response = client.put(
            path,
            data=json.dumps(payload(api_key="do-not-expose-this-key")),
            content_type="application/json",
        )
    assert response.status_code == 200
    provider.assert_not_called()
    config = ModelConfiguration.objects.get()
    assert config.encrypted_api_key and "do-not-expose" not in config.encrypted_api_key
    assert decrypt_key(config) == "do-not-expose-this-key"
    assert response.json()["has_api_key"]
    assert "do-not-expose" not in response.content.decode()
    assert "encrypted_api_key" not in response.json()
    assert AgentRun.objects.count() == 0
    unchanged = payload()
    unchanged.update(revision=1)
    assert (
        client.put(path, data=json.dumps(unchanged), content_type="application/json").status_code
        == 200
    )
    config.refresh_from_db()
    assert decrypt_key(config) == "do-not-expose-this-key"
    # Optimistic concurrency protects settings entered in another browser.
    assert (
        client.put(path, data=json.dumps(unchanged), content_type="application/json").status_code
        == 422
    )


def test_endpoint_changes_cannot_silently_forward_saved_credentials(
    actor, organization, configured
):
    values = payload()
    values.update(revision=1, base_url="https://api.openai.com/v1")
    with pytest.raises(ValidationError, match="Replace or remove"):
        save_configuration(actor, organization.id, ConfigurationInput(**values))
    for target in [
        "http://169.254.169.254/v1",
        "https://model.example/v1?token=x",
        "https://user@model.example/v1",
        "https://evil.example/v1",
    ]:
        values["base_url"] = target
        with pytest.raises(ValidationError, match="allowed"):
            save_configuration(actor, organization.id, ConfigurationInput(**values))
    values.update(base_url="https://api.openai.com/v1", clear_api_key=True)
    saved = save_configuration(actor, organization.id, ConfigurationInput(**values))
    assert not saved.has_api_key


def test_tenant_roles_csrf_and_disabled_default(client, actor, organization, market):
    base = f"/api/v1/organizations/{organization.id}/agent"
    assert (
        client.post(
            f"{base}/markets/{market.id}/runs",
            data=json.dumps({"idempotency_key": str(uuid4())}),
            content_type="application/json",
        ).status_code
        == 422
    )
    viewer = User.objects.create_user("agent-viewer@example.com", "password")
    OrganizationMembership.objects.create(organization=organization, user=viewer, role="VIEWER")
    client.force_login(viewer)
    assert client.get(f"{base}/status").status_code == 200
    assert client.get(f"{base}/configuration").status_code == 403
    assert (
        client.put(
            f"{base}/configuration", data=json.dumps(payload()), content_type="application/json"
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{base}/test",
            data=json.dumps({"idempotency_key": str(uuid4())}),
            content_type="application/json",
        ).status_code
        == 403
    )
    outsider = User.objects.create_superuser("outsider@example.com", "password")
    client.force_login(outsider)
    assert client.get(f"{base}/runs").status_code == 404
    assert client.get(f"{base}/configuration").status_code == 404
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(actor)
    assert (
        strict.put(
            f"{base}/configuration", data=json.dumps(payload()), content_type="application/json"
        ).status_code
        == 403
    )


def test_queue_idempotency_limits_cancel_and_cross_org_reads(
    client, actor, organization, market, configured
):
    key = uuid4()
    first = enqueue(actor, organization.id, key, market_id=market.id)
    assert enqueue(actor, organization.id, key, market_id=market.id).id == first.id
    with pytest.raises(ValidationError, match="already queued"):
        enqueue(actor, organization.id, uuid4(), market_id=market.id)
    other = create_organization(owner=actor, name="Another desk")
    assert client.get(f"/api/v1/organizations/{other.id}/agent/runs/{first.id}").status_code == 404
    cancel_run(actor, organization.id, first.id)
    configured.daily_run_limit = 1
    configured.save()
    with pytest.raises(ValidationError, match="daily request limit"):
        enqueue(actor, organization.id, uuid4(), market_id=market.id)


def test_frozen_cutoff_excludes_late_observations_and_news(market, rows):
    initialize_sources()
    source = EvidenceSource.objects.first()
    item = persist_entry(
        source,
        FeedEntry(
            "new",
            "Late news",
            "Evidence",
            "https://www.federalreserve.gov/newsevents/example.htm",
            timezone.now(),
        ),
    )
    EvidenceLink.objects.create(
        item=item, market=market, status="TOPIC_ONLY", rationale="Topic", method="test"
    )
    cutoff = datetime.fromisoformat(rows[-1]["recorded_at"])
    late = copy.deepcopy(rows[-1])
    late.update(observation_id=str(uuid4()), recorded_at=(cutoff + timedelta(days=1)).isoformat())
    repo = Mock()
    repo.history.return_value = [*rows, late]
    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        context = build_context(market.id, cutoff)
    assert len(context["observations"]) == len(rows)
    assert not any(ref["kind"] == "evidence" for ref in context["references"])
    assert any(ref["kind"] == "signal" for ref in context["references"])
    assert context["cutoff"] == cutoff.isoformat()


def test_job_publishes_validated_report_with_saved_context(
    actor, organization, market, configured, rows
):
    cutoff = datetime.fromisoformat(rows[-1]["recorded_at"])
    run = enqueue(actor, organization.id, uuid4(), market_id=market.id, cutoff=cutoff)
    repo = Mock()
    repo.history.return_value = rows
    provider = Mock(return_value=(json.dumps(report()), {"total_tokens": 90}))
    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        assert process_one(Event(), provider)
    run.refresh_from_db()
    assert run.state == "SUCCEEDED"
    assert run.report["action"] == "WATCH"
    assert run.context["observations"] == rows
    assert run.usage["total_tokens"] == 90
    assert "observations" not in json.loads(provider.call_args.args[2])["context"]
    assert not process_one(Event(), provider)
    provider.assert_called_once()


def test_invalid_citations_fail_without_exposing_raw_output(
    actor, organization, market, configured
):
    run = enqueue(actor, organization.id, uuid4(), market_id=market.id)
    with patch(
        "quanthecy.agents.worker.build_context",
        return_value={"references": [{"id": "market", "kind": "market"}]},
    ):
        process_one(
            Event(), Mock(return_value=(json.dumps(report("fabricated")), {"total_tokens": 42}))
        )
    run.refresh_from_db()
    assert run.state == "FAILED" and run.error_code == "invalid_report"
    assert run.report is None and run.usage == {"total_tokens": 42}
    assert run.validation_errors == [{"field": "thesis.references", "code": "unknown_reference"}]
    with pytest.raises(ValueError):
        validate_report(
            json.dumps({**report(), "confidence": 1.1}),
            {"references": [{"id": "market", "kind": "market"}]},
        )


def test_team_schema_failure_persists_redacted_field_diagnostics(
    client, actor, organization, configured, market, rows
):
    run = enqueue(actor, organization.id, uuid4(), market_id=market.id, workflow="team")
    repo = Mock(history=Mock(return_value=rows))
    invalid = team_output()
    invalid["summary"]["text"] = "secret-response" * 60
    invalid["secret-extra-key"] = "secret-extra-value"
    provider = Mock(return_value=(json.dumps(invalid), {"total_tokens": 40}))
    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        process_one(Event(), provider)
    run.refresh_from_db()
    assert run.state == "FAILED" and run.error_code == "invalid_report"
    assert run.steps[0]["validation_errors"] == run.validation_errors
    assert {i["code"] for i in run.validation_errors} == {"too_long", "extra_field"}
    assert run.steps[0]["output"] is None and run.report is None
    assert "secret" not in json.dumps(run.validation_errors)
    path = f"/api/v1/organizations/{organization.id}/agent/runs/{run.id}"
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["validation_errors"] == run.validation_errors
    provider.assert_called_once()


def test_configuration_change_during_call_discards_result(actor, organization, configured):
    run = enqueue(actor, organization.id, uuid4())

    def provider(*args):
        values = payload()
        values.update(revision=1, model="replacement")
        save_configuration(actor, organization.id, ConfigurationInput(**values))
        return '{"ok":true}', {"total_tokens": 5}

    process_one(Event(), provider)
    run.refresh_from_db()
    assert run.state == "CANCELLED" and run.report is None


def test_expired_worker_is_not_automatically_retried(actor, organization, configured):
    run = enqueue(actor, organization.id, uuid4())
    claimed = claim_run()
    assert claimed.id == run.id
    AgentRun.objects.filter(pk=run.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    expire_runs()
    assert claim_run() is None
    run.refresh_from_db()
    assert run.state == "FAILED" and run.error_code == "interrupted"


def test_adapter_bounds_output_redacts_errors_and_refuses_redirects():
    connection = Connection("openai", "https://api.openai.com/v1", "example", "secret-value")
    assert "secret-value" not in repr(connection)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.read.return_value = json.dumps(
        {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            "usage": {"total_tokens": 4},
        }
    ).encode()
    opener = Mock()
    opener.open.return_value = response
    with patch("quanthecy.agents.provider.build_opener", return_value=opener):
        raw, usage = complete(connection, "JSON", "Test")
        assert json.loads(raw) == {"ok": True} and usage == {"total_tokens": 4}
        sent = json.loads(opener.open.call_args.args[0].data)
        assert sent["max_completion_tokens"] == 2000 and sent["stream"] is False
        response.read.return_value = b"x" * 131073
        with pytest.raises(ProviderFailure, match="^provider_failed$"):
            complete(connection, "JSON", "Test")
    with pytest.raises(ProviderFailure):
        NoRedirect().redirect_request(None, None, 302, "", {}, "http://169.254.169.254/")


def test_anthropic_adapter_uses_messages_and_rejects_truncated_or_tool_output():
    connection = Connection("anthropic", "https://api.anthropic.com/v1", "example", "test-key")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    result = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": '{"ok":true}'}],
        "usage": {"input_tokens": 8, "output_tokens": 4},
    }
    opener = Mock()
    opener.open.return_value = response
    with patch("quanthecy.agents.provider.build_opener", return_value=opener):
        response.read.return_value = json.dumps(result).encode()
        text, usage = complete(connection, "Return JSON", "Test")
        assert json.loads(text) == {"ok": True}
        assert usage == {"prompt_tokens": 8, "completion_tokens": 4}
        request = opener.open.call_args.args[0]
        assert request.full_url == "https://api.anthropic.com/v1/messages"
        assert request.get_header("X-api-key") == "test-key"
        assert request.get_header("Anthropic-version") == "2023-06-01"
        assert not request.has_header("Authorization")
        body = json.loads(request.data)
        assert "system" in body and "response_format" not in body
        assert body["messages"] == [{"role": "user", "content": "Test"}]
        for invalid in [
            {**result, "stop_reason": "max_tokens"},
            {**result, "content": [{"type": "tool_use"}]},
            {**result, "content": ["not a block"]},
        ]:
            response.read.return_value = json.dumps(invalid).encode()
            with pytest.raises(ProviderFailure):
                complete(connection, "Return JSON", "Test")


def test_public_provider_configurations_save_without_any_model_requests(
    actor, organization, settings
):
    from quanthecy.agents.catalog import DEFAULT_ENDPOINTS

    settings.AGENT_ALLOWED_ENDPOINTS = list(DEFAULT_ENDPOINTS)
    with patch("quanthecy.agents.provider.complete") as provider:
        for revision, address in enumerate(DEFAULT_ENDPOINTS):
            values = payload()
            values.update(
                revision=revision,
                base_url=address,
                provider="anthropic" if "anthropic" in address else "openai_compatible",
                api_key="synthetic-storage-test",
            )
            saved = save_configuration(actor, organization.id, ConfigurationInput(**values))
            assert saved.base_url == address and saved.has_api_key and not saved.enabled
    provider.assert_not_called()
    assert not AgentRun.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_reserve_only_one_slot(actor, organization, configured):
    def submit(_):
        close_old_connections()
        try:
            enqueue(User.objects.get(pk=actor.pk), organization.id, uuid4())
            return "queued"
        except ValidationError:
            return "rejected"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(submit, range(2)))
    assert sorted(result) == ["queued", "rejected"]
    assert AgentRun.objects.count() == 1


def test_real_provider_subprocess_against_local_stub_only():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from quanthecy.agents.worker import bounded_complete

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["response_format"] == {"type": "json_object"}
            response = json.dumps(
                {
                    "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
                    "usage": {"total_tokens": 3},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = Connection(
            "openai_compatible", f"http://127.0.0.1:{server.server_port}/v1", "local-test", "", 256
        )
        raw, usage = bounded_complete(connection, "Return JSON.", "Test", Event())
        assert json.loads(raw) == {"ok": True}
        assert usage == {"total_tokens": 3}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, "provider_bad_request"),
        (401, "provider_auth"),
        (403, "provider_auth"),
        (402, "provider_quota"),
        (404, "provider_not_found"),
        (429, "provider_rate_limit"),
        (503, "provider_unavailable"),
    ],
)
def test_provider_errors_preserve_only_safe_categories(status, error):
    from urllib.error import HTTPError

    from quanthecy.agents.provider import child_complete

    connection = Connection("openai_compatible", "https://model.example/v1", "model", "secret")
    opener = Mock()
    opener.open.side_effect = HTTPError("https://model.example/v1", status, "secret-body", {}, None)
    with patch("quanthecy.agents.provider.build_opener", return_value=opener):
        with pytest.raises(ProviderFailure, match=f"^{error}$"):
            complete(connection, "JSON", "Test")
        pipe = Mock()
        child_complete(pipe, connection, "JSON", "Test")
        pipe.send.assert_called_once_with(("error", error))


def test_timeout_and_transport_errors_are_distinguishable():
    from urllib.error import URLError

    connection = Connection("openai_compatible", "https://model.example/v1", "model", "secret")
    opener = Mock()
    with patch("quanthecy.agents.provider.build_opener", return_value=opener):
        for exception, code in [
            (URLError(TimeoutError()), "provider_timeout"),
            (URLError("connection refused"), "provider_network"),
        ]:
            opener.open.side_effect = exception
            with pytest.raises(ProviderFailure, match=f"^{code}$"):
                complete(connection, "JSON", "Test")


def test_wrong_provider_and_missing_cloud_key_fail_before_enqueuing(actor, organization, settings):
    from quanthecy.agents.catalog import DEFAULT_ENDPOINTS

    settings.AGENT_ALLOWED_ENDPOINTS = list(DEFAULT_ENDPOINTS)
    values = payload()
    values.update(base_url="https://api.openai.com/v1", model="deepseek-flash")
    with pytest.raises(ValidationError, match="not served"):
        save_configuration(actor, organization.id, ConfigurationInput(**values))
    values.update(base_url="https://api.deepseek.com", enabled=True)
    with pytest.raises(ValidationError, match="API key"):
        save_configuration(actor, organization.id, ConfigurationInput(**values))
    config = ModelConfiguration.objects.create(
        organization=organization,
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        enabled=True,
    )
    with pytest.raises(ValidationError, match="API key"):
        enqueue(actor, organization.id, uuid4())
    from quanthecy.agents.services import status

    state = status(actor, organization.id)
    assert not state.can_run and state.configuration_issue == "missing_key"
    config.base_url = "https://api.openai.com/v1"
    config.save()
    with pytest.raises(ValidationError, match="not served"):
        enqueue(actor, organization.id, uuid4())
    assert not AgentRun.objects.exists()
