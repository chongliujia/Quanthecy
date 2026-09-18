import json
from datetime import timedelta
from threading import Event
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from quanthecy.agents.models import AgentRun, ModelConfiguration
from quanthecy.agents.worker import process_one
from quanthecy.paper.models import Account, Experiment, Opportunity
from quanthecy.paper.reviews import schedule_one
from quanthecy.paper.services import set_running, upgrade_experiment
from quanthecy.paper.views import lab, review_detail
from quanthecy_analytics.paper_review import validate_review
from test_paper import BASE, cycle
from test_paper import setup as paper_setup  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def upgraded(request):
    user, org, market, old = request.getfixturevalue("paper_setup")
    with patch("quanthecy.paper.services.timezone.now", return_value=BASE):
        experiment = upgrade_experiment(user, org.id)
    return user, org, market, old, experiment


def configure(org):
    return ModelConfiguration.objects.create(
        organization=org,
        provider="local",
        base_url="http://127.0.0.1:8088/v1",
        model="fixture",
        enabled=True,
        daily_run_limit=10,
        max_output_tokens=1000,
        context_window_tokens=8192,
        revision=1,
    )


def report(decision="ALLOW"):
    claim = {
        "kind": "OBSERVATION",
        "text": "Frozen evidence supports a simulated test.",
        "references": ["paper-entry"],
    }
    return {
        "decision": decision,
        "rationale": claim,
        "blocking_risks": [claim] if decision == "REJECT" else [],
        "cautions": [claim],
        "missing_evidence": [],
    }


def schedule(op, at=BASE):
    with (
        patch("quanthecy.paper.reviews.timezone.now", return_value=at),
        patch("quanthecy.paper.reviews.endpoint", return_value="http://127.0.0.1:8088/v1"),
    ):
        return schedule_one(op.id)


def completed(op, at=BASE + timedelta(seconds=10), result="ALLOW"):
    assert schedule(op)
    op.refresh_from_db()
    run = op.review_run
    run.state = "SUCCEEDED"
    run.started_at = BASE
    run.finished_at = at
    run.report = report(result)
    run.usage = {"provider_calls": 1, "prompt_tokens": 100, "completion_tokens": 50}
    run.save()
    return run


def test_upgrade_preserves_old_ledger_and_history_and_forbids_restarting_archive(upgraded):
    user, org, market, old, new = upgraded
    old.refresh_from_db()
    assert not old.running and new.running and new.version == "paper-v2"
    assert old.accounts.count() == 3 and old.accounts.first().ledger.count() == 1
    assert set(old.universe.values_list("market_id", flat=True)) == set(
        new.universe.values_list("market_id", flat=True)
    )
    with patch("quanthecy.paper.views.Redis.from_url", side_effect=OSError):
        assert lab(user, org.id).id == new.id
        assert lab(user, org.id, old.id).is_latest is False
    with pytest.raises(ValidationError):
        set_running(user, org.id, True, old.id)
    with pytest.raises(ValidationError):
        upgrade_experiment(user, org.id)
    assert Experiment.objects.count() == 2


def test_no_signal_no_model_call_and_disabled_model_is_visible(upgraded):
    _, _, market, _, new = upgraded
    market.probability_change_15m = 0.01
    market.save()
    cycle(new, market, BASE)
    assert not Opportunity.objects.exists()
    market.probability_change_15m = 0.03
    market.last_observed_at = BASE + timedelta(minutes=6)
    market.latest["observation_id"] = str(uuid4())
    market.save()
    cycle(new, market, BASE + timedelta(minutes=6))
    op = Opportunity.objects.get()
    assert not schedule(op, BASE + timedelta(minutes=6))
    op.refresh_from_db()
    assert op.reason == "review_model_unavailable" and not AgentRun.objects.exists()


def test_queue_is_idempotent_and_general_caution_does_not_block_entry(upgraded):
    user, org, market, _, new = upgraded
    configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    completed(op)
    assert not schedule(op, BASE + timedelta(seconds=11))
    assert AgentRun.objects.count() == 1
    cycle(new, market, BASE + timedelta(seconds=11))
    agent = Account.objects.get(experiment=new, strategy="agent_filtered")
    order = agent.orders.get()
    assert order.decision.phase == "REVIEW" and order.decision.reason == "review_allowed"
    assert order.decision.agent_run_id == AgentRun.objects.get().id
    cycle(new, market, BASE + timedelta(seconds=14))
    assert agent.orders.count() == 1 and agent.positions.get().quantity > 0
    op.refresh_from_db()
    assert op.state == "ALLOWED"
    detail = review_detail(user, org.id, op.id)
    assert detail.baseline_filled and detail.agent_filled
    with patch("quanthecy.paper.views.Redis.from_url", side_effect=OSError):
        summary = lab(user, org.id).review_summary
    assert (
        summary.paired_candidates == 1
        and summary.participation == 1
        and summary.provider_calls == 1
    )
    assert summary.model_cost_usd is None


@pytest.mark.parametrize("result, expected", [("REJECT", "REJECTED"), ("WAIT", "ABSTAINED")])
def test_review_rejection_and_abstention_are_distinct(upgraded, result, expected):
    _, org, market, _, new = upgraded
    configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    completed(op, result=result)
    cycle(new, market, BASE + timedelta(seconds=11))
    op.refresh_from_db()
    assert op.state == expected
    assert not new.accounts.get(strategy="agent_filtered").orders.exists()


@pytest.mark.parametrize("change", ["signal", "price", "rules", "configuration"])
def test_completed_review_rechecks_current_signal_contract_price_and_configuration(
    upgraded, change
):
    _, org, market, _, new = upgraded
    config = configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    completed(op)
    changes = {}
    if change == "signal":
        market.probability_change_15m = 0
    if change == "rules":
        market.latest["market"]["rules_version"] = "changed"
    if change == "configuration":
        config.revision += 1
        config.save()
    if change == "price":
        changes = {
            "bids": [{"price": "0.54", "size": "10000"}],
            "asks": [{"price": "0.55", "size": "10000"}],
        }
    market.save()
    cycle(new, market, BASE + timedelta(seconds=11), **changes)
    assert not new.accounts.get(strategy="agent_filtered").orders.exists()
    op.refresh_from_db()
    assert op.state == "INVALIDATED"


def test_daily_limit_and_busy_manual_queue_do_not_consume_new_calls(upgraded):
    user, org, market, _, new = upgraded
    config = configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    run = AgentRun.objects.create(
        organization=org,
        requested_by=user,
        kind="TEST",
        idempotency_key=uuid4(),
        cutoff=BASE,
        configuration_revision=1,
        provider="local",
        model="fixture",
    )
    AgentRun.objects.filter(pk=run.pk).update(created_at=BASE)
    assert not schedule(op)
    op.refresh_from_db()
    assert op.reason == "review_queue_busy"
    run.state = "SUCCEEDED"
    run.save()
    config.daily_run_limit = 1
    config.save()
    assert not schedule(op)
    op.refresh_from_db()
    assert op.reason == "review_daily_limit"
    assert AgentRun.objects.count() == 1


def test_pause_and_expiry_cancel_pending_reviews(upgraded):
    user, org, market, _, new = upgraded
    configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    assert schedule(op)
    set_running(user, org.id, False, new.id)
    op.refresh_from_db()
    assert op.state == "PAUSED" and op.review_run.state == "CANCELLED"
    cycle(new, market, BASE + timedelta(seconds=20))
    assert not new.accounts.get(strategy="agent_filtered").orders.exists()


def test_review_validator_rejects_unknown_evidence_and_inconsistent_allow():
    context = {"references": [{"id": "paper-entry"}]}
    assert validate_review(json.dumps(report()), context).decision == "ALLOW"
    invalid = report()
    invalid["blocking_risks"] = invalid["cautions"]
    with pytest.raises(ValueError):
        validate_review(json.dumps(invalid), context)
    invalid = report()
    invalid["rationale"]["references"] = ["fabricated"]
    with pytest.raises(ValueError):
        validate_review(json.dumps(invalid), context)


def test_agent_worker_uses_entry_review_schema_and_validates_before_publication(upgraded):
    _, org, market, _, new = upgraded
    configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    assert schedule(op)

    def complete(connection, system, prompt, stopped):
        payload = json.loads(prompt)
        assert "decision" in payload["report_schema"]["properties"]
        assert "virtual paper-trading" in system
        assert connection.max_output_tokens <= 2048
        return json.dumps(report()), {"prompt_tokens": 100, "completion_tokens": 50}

    with (
        patch("quanthecy.agents.worker.timezone.now", return_value=BASE + timedelta(seconds=1)),
        patch("quanthecy.agents.worker.endpoint", return_value="http://127.0.0.1:8088/v1"),
        patch(
            "quanthecy.agents.worker.build_context",
            return_value={"references": [], "observations": [], "cutoff": BASE.isoformat()},
        ),
    ):
        assert process_one(Event(), complete=complete)
    op.refresh_from_db()
    assert op.review_run.state == "SUCCEEDED", op.review_run.error_code
    assert op.review_run.usage["provider_calls"] == 1
    assert op.review_run.report["decision"] == "ALLOW"
    assert op.review_run.context["manifest"]["reference_count"] == 1


def test_expired_or_no_longer_eligible_signal_does_not_call_the_model(upgraded):
    from quanthecy.paper.reviews import schedule_reviews

    _, org, market, _, new = upgraded
    configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    market.probability_change_15m = 0
    market.save()
    assert not schedule(op)
    op.refresh_from_db()
    assert op.state == "INVALIDATED"
    op.state = "WAITING"
    op.expires_at = BASE
    op.save()
    with patch("quanthecy.paper.reviews.timezone.now", return_value=BASE):
        schedule_reviews()
    op.refresh_from_db()
    assert op.state == "EXPIRED"
    assert not AgentRun.objects.exists()


def test_review_details_and_experiment_history_are_tenant_scoped(upgraded):
    from django.http import Http404
    from quanthecy.accounts.models import User
    from quanthecy.organizations.models import OrganizationMembership
    from quanthecy.organizations.services import create_organization

    user, org, market, old, new = upgraded
    cycle(new, market, BASE)
    op = Opportunity.objects.get()
    other = create_organization(owner=user, name="Another")
    with pytest.raises(Http404):
        review_detail(user, other.id, op.id)
    with pytest.raises(Http404):
        lab(user, other.id, old.id)
    viewer = User.objects.create_user("review-viewer@example.com", "test-password")
    OrganizationMembership.objects.create(user=viewer, organization=org, role="VIEWER")
    with pytest.raises(PermissionDenied):
        set_running(viewer, org.id, False, new.id)
    assert review_detail(viewer, org.id, op.id).id == op.id
    client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
    client.force_login(user)
    assert (
        client.post(
            f"/api/v1/organizations/{org.id}/paper/upgrade",
            data="{}",
            content_type="application/json",
        ).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_schedulers_reserve_only_one_model_call(upgraded):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections
    from quanthecy.paper.reviews import schedule_one

    _, org, market, _, new = upgraded
    configure(org)
    cycle(new, market, BASE)
    op = Opportunity.objects.get()

    def reserve(_):
        close_old_connections()
        try:
            return schedule_one(op.id)
        finally:
            close_old_connections()

    with (
        patch("quanthecy.paper.reviews.timezone.now", return_value=BASE),
        patch("quanthecy.paper.reviews.endpoint", return_value="http://127.0.0.1:8088/v1"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        assert sorted(pool.map(reserve, range(2))) == [False, True]
    assert AgentRun.objects.filter(kind="PAPER_REVIEW").count() == 1
