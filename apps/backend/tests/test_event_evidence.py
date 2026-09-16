import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.agents.context import build_context
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import Market, ResearchTopic
from quanthecy.research.documents import OfficialDocument
from quanthecy.research.events import (
    append_definition,
    append_evidence_review,
    event_detail,
    event_list,
    sync_event_candidates,
)
from quanthecy.research.models import (
    EventDefinition,
    EventEvidence,
    EventEvidenceReview,
    EventMarketLink,
    EvidenceItem,
    EvidenceLink,
    EvidenceRevision,
    EvidenceSource,
    ResearchEvent,
)
from quanthecy.research.reviews import snapshot
from quanthecy_analytics.signals import analyze

pytestmark = pytest.mark.django_db
URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm"


@pytest.fixture
def event():
    topic = ResearchTopic.objects.create(slug="test-fed", name="Fed")
    event = ResearchEvent.objects.create(slug="test-fed", topic=topic)
    definition = EventDefinition(
        event=event,
        title="October Fed meeting",
        scope="Research October, not July.",
        starts_on=date(2026, 10, 27),
        ends_on=date(2026, 10, 28),
        calendar_url=URL,
        source_slugs=["fed-monetary"],
    )
    append_definition(definition)
    return event


def revision(item, version=1):
    now = timezone.now()
    text = (
        "The committee considers employment and inflation in its decision. " * 3
        + "\n\nThis release concerns July only."
    )
    document = OfficialDocument(
        url=URL,
        title="Official fixture",
        kind="MONETARY_RELEASE",
        text=text,
        observed_at=now,
        raw_sha256="a" * 64,
        text_sha256="b" * 64,
    )
    return EvidenceRevision.objects.create(
        item=item,
        version=version,
        title=f"Official fixture {version}",
        excerpt="Feed excerpt",
        url=URL,
        published_at=now - timedelta(days=1),
        observed_at=now,
        content_hash="c" * 64,
        document=document.model_dump(mode="json"),
        raw_document="<script>private raw</script>",
    )


@pytest.fixture
def candidate(event):
    source = EvidenceSource.objects.create(slug="fed-monetary", name="Fed", url=URL)
    item = EvidenceItem.objects.create(source=source, external_id="fixture")
    revision(item)
    assert sync_event_candidates() == 1
    return EventEvidence.objects.get()


@pytest.fixture
def operator():
    return User.objects.create_superuser("event-operator@example.com", "test-only-password")


def review(candidate, operator, relation="DIRECT", paragraphs=None):
    value = EventEvidenceReview(
        candidate=candidate,
        reviewed_by=operator,
        relation=relation,
        rationale="Applicable to the event with an explicit timing qualification.",
        paragraphs=[2] if paragraphs is None else paragraphs,
    )
    append_evidence_review(value)
    return value


def test_candidate_discovery_never_approves_and_is_idempotent(event, candidate):
    assert sync_event_candidates() == 0
    data = event_detail(event.slug, None)
    assert data.counts["PENDING"] == 1 and data.counts["DIRECT"] == 0
    assert any(c.kind == "EVIDENCE" for c in data.changes)
    assert not EventEvidenceReview.objects.exists()
    assert not event_list(event.created_at - timedelta(microseconds=1))


@pytest.mark.parametrize("paragraphs", [[], [0], [3], [1, 1], [True], ["1"], {"x": 1}])
def test_direct_review_requires_valid_original_paragraph(candidate, operator, paragraphs):
    with pytest.raises(ValidationError):
        review(candidate, operator, paragraphs=paragraphs)
    assert not EventEvidenceReview.objects.exists()


def test_reviews_are_append_only_and_cutoff_safe(event, candidate, operator):
    before = timezone.now()
    first = review(candidate, operator)
    after_first = timezone.now()
    review(candidate, operator, "BACKGROUND", [])
    assert event_detail(event.slug, before).counts["PENDING"] == 1
    earlier = event_detail(event.slug, after_first)
    assert earlier.evidence[0].review.id == first.pk
    assert earlier.evidence[0].passages[0].paragraph == 2
    assert earlier.evidence[0].passages[0].text == "This release concerns July only."
    latest = event_detail(event.slug, None)
    assert latest.counts["BACKGROUND"] == 1 and len(latest.evidence[0].history) == 2
    with pytest.raises(ValidationError):
        first.save()
    with pytest.raises(ValidationError):
        first.delete()


def test_changed_document_invalidates_review_before_worker_and_rejects_stale_forms(
    event, candidate, operator
):
    review(candidate, operator)
    before = timezone.now()
    new = revision(candidate.revision.item, 2)
    assert event_detail(event.slug, None).counts["STALE"] == 1
    with pytest.raises(ValidationError, match="newer version"):
        review(candidate, operator)
    assert sync_event_candidates() == 1
    detail = event_detail(event.slug, None)
    assert detail.counts["PENDING"] == 1 and detail.evidence[0].evidence.revision_id == new.id
    assert event_detail(event.slug, before).counts["DIRECT"] == 1


def test_changed_scope_requires_new_reviews_and_preserves_history(event, candidate, operator):
    review(candidate, operator)
    cutoff = timezone.now()
    previous = event.definitions.get()
    new = EventDefinition(
        event=event,
        title="Revised scope",
        scope="Different outcome scope.",
        starts_on=previous.starts_on,
        ends_on=previous.ends_on,
        calendar_url=URL,
        source_slugs=["fed-monetary"],
    )
    append_definition(new)
    assert event_detail(event.slug, None).event.version == 2
    assert not event_detail(event.slug, None).evidence
    with pytest.raises(ValidationError, match="newer version"):
        review(candidate, operator)
    sync_event_candidates()
    assert event_detail(event.slug, None).counts["PENDING"] == 1
    assert event_detail(event.slug, cutoff).counts["DIRECT"] == 1


def test_customer_api_auth_provenance_and_private_field_boundaries(event, candidate, operator):
    review(candidate, operator)
    client = Client()
    url = f"/api/v1/research/events/{event.slug}"
    assert client.get(url).status_code == 401
    client.force_login(User.objects.create_user("event-reader@example.com"))
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert "raw_document" not in body and "private raw" not in body and operator.email not in body
    data = response.json()["evidence"][0]["evidence"]
    exact = client.get(f"/api/v1/evidence/{data['id']}", {"cutoff": data["observed_at"]})
    assert exact.json()["item"]["revision_id"] == str(candidate.revision_id)
    assert client.post(url, {}).status_code == 405


def test_admin_review_form_permission_validation_and_csrf(candidate, operator):
    client = Client()
    reader = User.objects.create_user("ordinary-reviewer@example.com")
    client.force_login(reader)
    url = f"/admin/research/eventevidencereview/add/?candidate={candidate.pk}"
    assert client.get(url).status_code == 302
    with pytest.raises(PermissionDenied):
        review(candidate, reader)
    client.force_login(operator)
    form = {
        "candidate": str(candidate.pk),
        "relation": "DIRECT",
        "rationale": "Timing qualification.",
        "paragraphs": "[2]",
        "_save": "Save",
    }
    assert client.get(url, {"candidate": candidate.pk}).status_code == 200
    invalid = client.post(url, {**form, "paragraphs": "[99]"})
    assert invalid.status_code == 200 and not EventEvidenceReview.objects.exists()
    assert client.post("/admin/research/eventevidencereview/add/", form).status_code == 200
    assert not EventEvidenceReview.objects.exists()
    assert client.post(url, form).status_code == 302
    saved = EventEvidenceReview.objects.get()
    assert saved.reviewed_by == operator and saved.paragraphs == [2]
    assert client.get("/admin/research/eventevidence/?review_state=reviewed").status_code == 200
    guarded = Client(enforce_csrf_checks=True)
    guarded.force_login(operator)
    assert guarded.post(url, form).status_code == 403
    revision(candidate.revision.item, 2)
    assert client.post(url, form).status_code == 200
    assert EventEvidenceReview.objects.count() == 1


def test_agent_prioritizes_reviewed_paragraphs_excludes_rejected_and_withholds_unreviewed(
    event, candidate, operator
):
    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )
    now = timezone.now() - timedelta(seconds=2)
    shift = now - datetime.fromisoformat(rows[-1]["recorded_at"])
    for row in rows:
        for key in ("received_at", "recorded_at"):
            row[key] = (datetime.fromisoformat(row[key]) + shift).isoformat()
        row["probability"]["as_of"] = row["received_at"]
        row["market"]["closes_at"] = (now + timedelta(days=30)).isoformat()
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    market = Market.objects.get()
    EventMarketLink.objects.create(event=event, market=market, snapshot=snapshot(market))
    EvidenceLink.objects.create(item=candidate.revision.item, market=market, rationale="Topic only")
    repo = Mock()
    repo.history.return_value = rows
    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        pending = build_context(market.pk, timezone.now())
        assert not pending["quality"]["forecast_eligible"]
        assert pending["quality"]["reviewed_evidence_ids"] == []
        review(candidate, operator)
        direct = build_context(market.pk, timezone.now())
        assert direct["quality"]["forecast_eligible"]
        ref = next(r for r in direct["references"] if r["kind"] == "evidence")
        assert direct["quality"]["reviewed_evidence_ids"] == [str(candidate.revision_id)]
        assert ref["value"]["document_selection"]["passages"][0]["paragraph"] == 2
        assert ref["value"]["event_reviews"][0]["review"]["relation"] == "DIRECT"
        review(candidate, operator, "UNRELATED", [])
        rejected = build_context(market.pk, timezone.now())
        assert not any(r["kind"] == "evidence" for r in rejected["references"])
        assert not rejected["quality"]["forecast_eligible"]
        assert "event-operator" not in json.dumps(direct)


def test_private_topic_and_future_publication_are_not_discovered(event):
    source = EvidenceSource.objects.create(slug="fed-monetary", name="Fed", url=URL)
    item = EvidenceItem.objects.create(source=source, external_id="future")
    value = revision(item)
    EvidenceRevision.objects.filter(pk=value.pk).update(
        published_at=timezone.now() + timedelta(days=1)
    )
    assert sync_event_candidates() == 0
    event.topic.is_public = False
    event.topic.save()
    assert event_list(None) == []


def test_admin_binds_review_to_preview_even_if_candidate_post_is_tampered(candidate, operator):
    item = EvidenceItem.objects.create(source=candidate.revision.item.source, external_id="other")
    revision(item)
    sync_event_candidates()
    other = EventEvidence.objects.exclude(pk=candidate.pk).get()
    client = Client()
    client.force_login(operator)
    url = f"/admin/research/eventevidencereview/add/?candidate={candidate.pk}"
    response = client.post(
        url,
        {
            "candidate": str(other.pk),
            "relation": "DIRECT",
            "rationale": "Applies to the previewed source.",
            "paragraphs": "[2]",
            "_save": "Save",
        },
    )
    assert response.status_code == 302, response.context["adminform"].form.errors
    assert EventEvidenceReview.objects.get().candidate_id == candidate.pk
    invalid = client.post(
        url,
        {
            "candidate": str(other.pk),
            "relation": "DIRECT",
            "rationale": "Test",
            "paragraphs": "[99]",
        },
    )
    assert invalid.status_code == 200
    assert invalid.context["review_candidate"].pk == candidate.pk
