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


def expand(event, sources=None):
    previous = event.definitions.latest("version")
    value = EventDefinition(
        event=event,
        title=previous.title,
        scope=previous.scope,
        starts_on=previous.starts_on,
        ends_on=previous.ends_on,
        calendar_url=URL,
        source_slugs=sources or ["fed-monetary", "bbc-business", "bea-releases"],
        discovery_policy="fed-macro-v1",
    )
    append_definition(value)
    return value


def test_content_discovery_rejects_unrelated_and_old_items(event):
    from quanthecy.research.discovery import discover

    definition = expand(event)
    source = EvidenceSource.objects.create(slug="bbc-business", name="BBC", url=URL)
    item = EvidenceItem.objects.create(source=source, external_id="macro")
    value = EvidenceRevision(
        item=item,
        version=1,
        title="Federal Reserve interest rates in October 2026",
        excerpt="US inflation report",
        published_at=timezone.make_aware(datetime(2026, 9, 1)),
    )
    result = discover(definition, value)
    assert result["priority"] == 30
    assert "EVENT_MONTH_MENTION" in result["reasons"]
    assert result["matches"][0]["text"] == value.title
    value.title, value.excerpt = "A technology launch", "International business"
    assert discover(definition, value) is None
    value.title = "UK inflation rises"
    assert discover(definition, value) is None
    value.title = "US inflation rises"
    assert discover(definition, value)["priority"] == 10
    value.published_at = timezone.make_aware(datetime(2025, 1, 1))
    assert discover(definition, value) is None
    value.published_at = None
    assert "PUBLICATION_UNKNOWN" in discover(definition, value)["reasons"]


def test_content_policy_is_explicit_and_old_scope_remains(event, candidate):
    from quanthecy.research.feeds import FeedEntry
    from quanthecy.research.news import persist_entry

    definition = expand(event)
    source = EvidenceSource.objects.create(slug="bbc-business", name="BBC", url=URL)
    saved = persist_entry(
        source,
        FeedEntry(
            "bbc",
            "Federal Reserve interest rates",
            "US inflation outlook",
            "https://www.bbc.com/news/example",
            timezone.now() - timedelta(days=1),
        ),
    )
    assert sync_event_candidates() >= 1
    match = EventEvidence.objects.get(definition=definition, revision__item=saved)
    assert match.discovery_priority == 20 and match.discovery["matches"]
    assert match.reviews.count() == 0
    assert candidate.definition.discovery_policy == "source-only-v1"
    assert sync_event_candidates() == 0


def make_market_history(event):
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
    link = EventMarketLink.objects.create(event=event, market=market, snapshot=snapshot(market))
    repo = Mock()
    repo.history.return_value = rows
    return market, link, repo


def test_media_quote_and_stance_are_preserved_but_cannot_unlock_forecast(event, operator):
    definition = expand(event)
    source = EvidenceSource.objects.create(slug="bbc-business", name="BBC", url=URL)
    item = EvidenceItem.objects.create(source=source, external_id="media")
    value = EvidenceRevision.objects.create(
        item=item,
        version=1,
        title="Federal Reserve interest rate outlook",
        excerpt="US inflation slowed according to a report.",
        url="https://www.bbc.com/news/example",
        content_hash="d" * 64,
        published_at=timezone.now() - timedelta(days=1),
    )
    sync_event_candidates()
    candidate = EventEvidence.objects.get(definition=definition, revision=value)
    market, target, repo = make_market_history(event)
    reviewed = EventEvidenceReview(
        candidate=candidate,
        relation="DIRECT",
        feed_quote=value.excerpt,
        stance="SUPPORTS",
        target_contract=target,
        rationale="Conditional support for this saved outcome only.",
        paragraphs=[],
        reviewed_by=operator,
    )
    append_evidence_review(reviewed)
    data = event_detail(event.slug, None)
    assert data.counts["DIRECT"] == 1 and data.official_direct_count == 0
    assert data.evidence[0].review.stance == "SUPPORTS"
    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        context = build_context(market.pk, timezone.now())
        assert not context["quality"]["forecast_eligible"]
        ref = next(r for r in context["references"] if r["kind"] == "evidence")
        saved = ref["value"]["event_reviews"][0]["review"]
        assert saved["stance_applicable"] and saved["feed_quote"] == value.excerpt
        repo.history.return_value[-1]["market"]["resolution_rules"] = "Changed rules"
        changed = build_context(market.pk, timezone.now())
        ref = next(r for r in changed["references"] if r["kind"] == "evidence")
        assert not ref["value"]["event_reviews"][0]["review"]["stance_applicable"]


@pytest.mark.parametrize(
    "changes",
    [
        {"stance": "SUPPORTS"},
        {"feed_quote": "This quote was invented entirely."},
        {"stance": "INVALID"},
    ],
)
def test_review_rejects_unbound_direction_or_invented_quote(candidate, operator, changes):
    value = EventEvidenceReview(
        candidate=candidate,
        relation="DIRECT",
        paragraphs=[2],
        rationale="Review",
        reviewed_by=operator,
        **changes,
    )
    with pytest.raises(ValidationError):
        append_evidence_review(value)


def test_stance_cannot_target_another_event_or_changed_rules(event, candidate, operator):
    market, target, _ = make_market_history(event)
    other = ResearchEvent.objects.create(slug="other-event", topic=event.topic)
    wrong = EventMarketLink.objects.create(event=other, market=market, snapshot=target.snapshot)
    value = EventEvidenceReview(
        candidate=candidate,
        relation="DIRECT",
        paragraphs=[2],
        rationale="Review",
        reviewed_by=operator,
        stance="OPPOSES",
        target_contract=wrong,
    )
    with pytest.raises(ValidationError, match="linked to this event"):
        append_evidence_review(value)
    value.target_contract = target
    market.latest["market"]["resolution_rules"] = "Changed"
    market.save()
    with pytest.raises(ValidationError, match="rules or outcome changed"):
        append_evidence_review(value)


def test_saved_version_changes_are_cutoff_safe_and_distinguish_capture(event, candidate):
    before = timezone.now()
    previous = candidate.revision
    new = revision(previous.item, 2)
    body = new.document.copy()
    body["text"] = (
        "A new policy paragraph with updated qualifications. " * 3
        + "\n\nThis release concerns July only."
    )
    EvidenceRevision.objects.filter(pk=new.pk).update(document=body, excerpt="Changed excerpt")
    sync_event_candidates()
    data = event_detail(event.slug, None).evidence[0].changes
    assert data["previous_revision_id"] == str(previous.id)
    assert data["added"][0]["paragraph"] == 1
    assert data["removed"][0]["paragraph"] == 1
    assert {"excerpt", "document"} <= set(data["changed_fields"])
    earlier = event_detail(event.slug, before).evidence[0].changes
    assert earlier["kind"] == "FIRST_OBSERVED" and not earlier["added"]
