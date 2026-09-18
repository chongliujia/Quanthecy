import copy
import json
from datetime import timedelta
from threading import Event
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from quanthecy.agents import assistants
from quanthecy.agents.assistant_schemas import AssistantSave
from quanthecy.agents.models import AgentRun, AssistantVersion
from quanthecy.agents.schemas import RunDetail
from quanthecy.agents.worker import process_one
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.services import create_organization
from quanthecy.paper.models import Account, Opportunity, Order
from quanthecy.paper.services import create_experiment, set_running
from quanthecy.paper.views import lab, order_detail
from quanthecy_analytics.assistant import AssistantGraph
from test_paper import BASE, cycle
from test_paper import setup as paper_setup  # noqa: F401
from test_paper_reviews import configure, report, schedule

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def assistant_setup(request):
    user, org, market, old = request.getfixturevalue("paper_setup")
    assistant = assistants.create(user, org.id, "My team", None)
    version = assistants.publish(user, org.id, assistant.id, assistant.revision)
    return user, org, market, old, assistant, version


def comparison(values):
    user, org, market, old, assistant, version = values
    with patch("quanthecy.paper.services.timezone.now", return_value=BASE):
        return create_experiment(
            user,
            org.id,
            [market.id],
            old.accounts.first().initial_cash,
            "Comparison",
            version="paper-v3",
            assistant_version_ids=[version.id],
        )


def context():
    return {
        "version": "context-v6",
        "cutoff": BASE.isoformat(),
        "observations": [],
        "references": [
            {"id": "market", "kind": "market", "label": "Market", "value": {}},
            {"id": "rules", "kind": "rules", "label": "Rules", "value": {}},
        ],
        "limitations": [],
        "quality": {},
    }


def provider(connection, system, prompt, stopped):
    packet = json.loads(prompt)
    if "decision" in packet["output_schema"]["properties"]:
        result = report()
        result["rationale"]["references"] = ["market"]
        result["cautions"] = []
    else:
        result = {
            "summary": {
                "kind": "OBSERVATION",
                "text": "Frozen evidence.",
                "references": ["market"],
            },
            "findings": [],
            "challenges": [],
            "limitations": [],
            "watch_for": [],
        }
    return json.dumps(result), {"prompt_tokens": 10, "completion_tokens": 5}


def run_worker(complete=provider):
    with (
        patch("quanthecy.agents.worker.timezone.now", return_value=BASE + timedelta(seconds=10)),
        patch("quanthecy.agents.worker.endpoint", return_value="http://127.0.0.1:8088/v1"),
        patch("quanthecy.agents.worker.build_context", return_value=context()),
    ):
        assert process_one(Event(), complete)


def test_published_versions_survive_draft_edits_and_stale_edits_fail(assistant_setup):
    user, org, _, _, assistant, version = assistant_setup
    frozen = copy.deepcopy(version.graph)
    graph = AssistantGraph.model_validate(assistant.draft)
    graph.nodes[0].instructions = "Check the event timing."
    saved = assistants.save(
        user, org.id, assistant.id, AssistantSave(name="Renamed", revision=1, graph=graph)
    )
    with pytest.raises(ValidationError):
        assistants.publish(user, org.id, assistant.id, 1)
    second = assistants.publish(user, org.id, assistant.id, saved.revision)
    assert second.number == 2 and second.graph != frozen
    assert assistants.publish(user, org.id, assistant.id, saved.revision).id == second.id
    version.refresh_from_db()
    assert version.graph == frozen and version.name == "My team"


def test_comparison_freezes_versions_and_keeps_previous_accounts(assistant_setup):
    user, org, market, old, assistant, version = assistant_setup
    before = list(old.accounts.values_list("id", "cash"))
    experiment = comparison(assistant_setup)
    old.refresh_from_db()
    assert not old.running and experiment.running
    assert experiment.accounts.count() == 4
    assert list(old.accounts.values_list("id", "cash")) == before
    assert experiment.accounts.filter(assistant_version=version).count() == 1
    with pytest.raises(ValidationError):
        set_running(user, org.id, True, old.id)
    again = comparison(assistant_setup)
    experiment.refresh_from_db()
    assert again.id != experiment.id and not experiment.running


def test_five_node_langgraph_review_then_simulated_fill(assistant_setup):
    user, org, market, _, assistant, version = assistant_setup
    configure(org)
    experiment = comparison(assistant_setup)
    cycle(experiment, market, BASE)
    op = Opportunity.objects.get(account__assistant_version=version)
    assert schedule(op)
    op.refresh_from_db()
    assert op.review_run.reserved_calls == 5
    assert not schedule(op)
    run_worker()
    run = AgentRun.objects.get(id=op.review_run_id)
    assert run.state == "SUCCEEDED", (run.error_code, run.validation_errors)
    assert len(run.steps) == 5 and run.usage["provider_calls"] == 5
    assert run.steps[-1]["output"]["decision"] == "ALLOW"
    assert len(run.steps[-2]["input_packet"]["peer_findings"]) == 3
    assert all(not step["input_packet"]["peer_findings"] for step in run.steps[:3])
    RunDetail.from_orm(run)
    client = Client()
    client.force_login(user)
    summary = client.get(f"/api/v1/organizations/{org.id}/assistants/runs")
    assert summary.status_code == 200 and summary.json()[0]["reserved_calls"] == 5
    assert "steps" not in summary.json()[0]
    detail = client.get(f"/api/v1/organizations/{org.id}/agent/runs/{run.id}")
    assert detail.status_code == 200 and detail.json()["steps"][0]["input_packet"]
    cycle(experiment, market, BASE + timedelta(seconds=11))
    cycle(experiment, market, BASE + timedelta(seconds=14))
    account = Account.objects.get(experiment=experiment, assistant_version=version)
    assert account.positions.get().quantity > 0
    assert order_detail(user, org.id, account.orders.get().id).replay_matches is True
    with patch("quanthecy.paper.views.Redis.from_url", side_effect=OSError):
        result = lab(user, org.id)
    stats = next(a.review_summary for a in result.accounts if a.id == account.id)
    assert stats.provider_calls == 5 and stats.participation == 1
    assert sum(account.ledger.values_list("cash_delta", flat=True)) == account.cash


def test_failed_node_prevents_later_calls_and_orders(assistant_setup):
    _, org, market, _, _, version = assistant_setup
    configure(org)
    experiment = comparison(assistant_setup)
    cycle(experiment, market, BASE)
    op = Opportunity.objects.get(account__assistant_version=version)
    assert schedule(op)
    calls = []

    def invalid(*args):
        calls.append(1)
        return '{"wrong": true}', {}

    run_worker(invalid)
    run = AgentRun.objects.get()
    assert run.state == "FAILED" and run.error_code == "invalid_report"
    assert len(calls) == 1
    cycle(experiment, market, BASE + timedelta(seconds=12))
    assert not Order.objects.filter(account__assistant_version=version).exists()


def test_trial_is_frozen_idempotent_and_never_creates_orders(assistant_setup):
    user, org, market, _, assistant, _ = assistant_setup
    configure(org)
    key = uuid4()
    with (
        patch("quanthecy.agents.services.timezone.now", return_value=BASE),
        patch("quanthecy.agents.services.endpoint", return_value="http://127.0.0.1:8088/v1"),
    ):
        run = assistants.trial(user, org.id, assistant.id, 1, market.id, key)
        assert assistants.trial(user, org.id, assistant.id, 1, market.id, key).id == run.id
    original_hash = run.assistant_graph_hash
    edited = AssistantGraph.model_validate(assistant.draft)
    edited.nodes[0].instructions = "A later edit must not reach the queued run."
    assistants.save(
        user, org.id, assistant.id, AssistantSave(name="Later name", revision=1, graph=edited)
    )
    run_worker()
    run.refresh_from_db()
    assert run.state == "SUCCEEDED" and run.assistant_version_id is None
    assert run.assistant_graph_hash == original_hash and run.assistant_name == "My team"
    assert all("A later edit" not in json.dumps(step["input_packet"]) for step in run.steps)
    assert not Opportunity.objects.exists() and not Order.objects.exists()


def test_additional_signal_filter_rejects_before_model_admission(assistant_setup):
    user, org, market, old, assistant, _ = assistant_setup
    graph = AssistantGraph.model_validate(assistant.draft)
    graph.entry_change_15m = 0.05
    saved = assistants.save(
        user, org.id, assistant.id, AssistantSave(name="Higher threshold", revision=1, graph=graph)
    )
    version = assistants.publish(user, org.id, assistant.id, saved.revision)
    configure(org)
    experiment = comparison((user, org, market, old, saved, version))
    cycle(experiment, market, BASE)
    op = Opportunity.objects.get(account__assistant_version=version)
    assert not schedule(op)
    op.refresh_from_db()
    assert op.state == "INVALIDATED" and op.reason == "assistant_signal_filter"
    assert not AgentRun.objects.exists()


def test_pause_during_a_node_preserves_usage_and_prevents_publication(assistant_setup):
    user, org, market, _, _, version = assistant_setup
    configure(org)
    experiment = comparison(assistant_setup)
    cycle(experiment, market, BASE)
    assert schedule(Opportunity.objects.get(account__assistant_version=version))
    calls = []

    def stop_during_call(*args):
        calls.append(1)
        set_running(user, org.id, False, experiment.id)
        return provider(*args)

    run_worker(stop_during_call)
    run = AgentRun.objects.get()
    assert len(calls) == 1 and run.state == "CANCELLED" and run.report is None
    assert run.usage["provider_calls"] == 1 and run.steps[0]["state"] == "CANCELLED"
    assert run.usage["completion_tokens"] == 5


def test_quota_counts_every_node_and_pause_cancels_graph(assistant_setup):
    user, org, market, _, _, version = assistant_setup
    config = configure(org)
    config.daily_run_limit = 4
    config.save()
    experiment = comparison(assistant_setup)
    cycle(experiment, market, BASE)
    op = Opportunity.objects.get(account__assistant_version=version)
    assert not schedule(op)
    op.refresh_from_db()
    assert op.reason == "review_daily_limit"
    config.daily_run_limit = 10
    config.save()
    assert schedule(op)
    set_running(user, org.id, False, experiment.id)
    run = AgentRun.objects.get()
    assert run.state == "CANCELLED"


def test_workspace_isolation_viewer_and_csrf(assistant_setup):
    user, org, market, _, assistant, version = assistant_setup
    other = create_organization(owner=user, name="Other")
    client = Client()
    client.force_login(user)
    base = f"/api/v1/organizations/{other.id}/assistants"
    response = client.put(
        f"{base}/{assistant.id}",
        data=json.dumps({"name": "bad", "revision": 1, "graph": assistant.draft}),
        content_type="application/json",
    )
    assert response.status_code == 404
    response = client.post(
        base,
        data=json.dumps({"name": "Copy", "source_id": str(assistant.id)}),
        content_type="application/json",
    )
    assert response.status_code == 404
    with pytest.raises(ValidationError):
        create_experiment(
            user,
            other.id,
            [market.id],
            10000,
            "Cross tenant",
            version="paper-v3",
            assistant_version_ids=[version.id],
        )
    OrganizationMembership.objects.filter(user=user, organization=org).update(role="VIEWER")
    with pytest.raises(PermissionDenied):
        assistants.publish(user, org.id, assistant.id, 1)
    assert client.get(f"/api/v1/organizations/{org.id}/assistants").status_code == 200
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(user)
    assert (
        strict.post(base, data='{"name":"Blocked"}', content_type="application/json").status_code
        == 403
    )
    assert AssistantVersion.objects.filter(assistant=assistant).count() == 1


def test_prompt_skills_saved_by_api_are_frozen_and_used_in_langgraph(assistant_setup):
    user, org, market, _, assistant, _ = assistant_setup
    client = Client()
    client.force_login(user)
    graph = copy.deepcopy(assistant.draft)
    graph["nodes"][0].update(
        prompt="Examine settlement ambiguity.",
        skills=[
            {"name": "SKILL.md", "content": "# Method\nRead the supplied rules.", "enabled": True},
            {"name": "off.md", "content": "Disabled private method", "enabled": False},
        ],
    )
    path = f"/api/v1/organizations/{org.id}/assistants/{assistant.id}"
    response = client.put(
        path,
        data=json.dumps({"name": assistant.name, "revision": 1, "graph": graph}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["draft"]["nodes"][0]["skills"] == graph["nodes"][0]["skills"]
    version = assistants.publish(user, org.id, assistant.id, 2)
    assert version.graph["nodes"][0]["prompt"] == "Examine settlement ambiguity."
    configure(org)
    with (
        patch("quanthecy.agents.services.timezone.now", return_value=BASE),
        patch("quanthecy.agents.services.endpoint", return_value="http://127.0.0.1:8088/v1"),
    ):
        run = assistants.trial(user, org.id, assistant.id, 2, market.id, uuid4())
    graph["nodes"][0]["skills"][0]["content"] = "Later changed method"
    assistants.save(
        user,
        org.id,
        assistant.id,
        AssistantSave(name=assistant.name, revision=2, graph=AssistantGraph.model_validate(graph)),
    )
    sent = []

    def capture(connection, system, prompt, stopped):
        sent.append((system, json.loads(prompt)))
        return provider(connection, system, prompt, stopped)

    run_worker(capture)
    run.refresh_from_db()
    version.refresh_from_db()
    assert run.state == "SUCCEEDED" and len(sent) == 5
    packets = [packet for _, packet in sent if "assistant_prompt" in packet]
    assert len(packets) == 1
    assert packets[0]["assistant_skills"] == [
        {"name": "SKILL.md", "content": "# Method\nRead the supplied rules."}
    ]
    assert "Later changed" not in json.dumps(run.steps)
    assert "Disabled private method" not in json.dumps(run.steps)
    assert version.graph["nodes"][0]["skills"][0]["content"] != "Later changed method"
    assert not Order.objects.exists()
    graph["nodes"][0]["skills"][0]["name"] = "../SKILL.md"
    invalid = client.put(
        path,
        data=json.dumps({"name": assistant.name, "revision": 3, "graph": graph}),
        content_type="application/json",
    )
    assert invalid.status_code == 422
