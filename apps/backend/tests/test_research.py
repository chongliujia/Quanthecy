import copy
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from defusedxml.common import DefusedXmlException
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import Event, Market
from quanthecy.research import services
from quanthecy.research.feeds import FeedEntry, parse_feed
from quanthecy.research.models import (
    Comparison,
    ComparisonReview,
    EvidenceLink,
    EvidenceRevision,
    EvidenceSource,
)
from quanthecy.research.news import (
    associate_topics,
    initialize_sources,
    persist_entry,
    poll_one_source,
)
from quanthecy.research.reviews import append_review
from quanthecy_analytics.signals import analyze
from quanthecy_analytics.storage.clickhouse import AnalyticsUnavailable, ClickHouseRepository

pytestmark = pytest.mark.django_db


@pytest.fixture
def market():
    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    market = Market.objects.get()
    market.title = "Fed decision in September?"
    market.save()
    return market


@pytest.fixture
def pair(market):
    event = Event.objects.create(
        id=uuid4(), platform="kalshi", exchange_id="FED", title="Fed", observed_at=timezone.now()
    )
    right = Market.objects.create(
        id=uuid4(),
        event=event,
        platform="kalshi",
        exchange_id="KXFED-H0",
        title="Fed decision?",
        status="OPEN",
        first_observed_at=market.first_observed_at,
        last_observed_at=market.last_observed_at,
        latest=copy.deepcopy(market.latest),
        metrics=market.metrics,
    )
    right.latest["market"]["id"] = str(right.id)
    right.latest["market"]["exchange_id"] = right.exchange_id
    right.latest["outcome"]["id"] = str(uuid4())
    right.save()
    return Comparison.objects.create(slug="fed-no-change", left=market, right=right)


@pytest.fixture
def reviewer(pair):
    def create(**changes):
        values = dict(
            comparison=pair,
            title="Fed no change",
            relation="RELATED",
            alignment="SAME",
            confidence=0.9,
            rationale="Same scheduled meeting.",
            differences="Cancellation fallback differs.",
            reviewer_label="Test source review",
        )
        values.update(changes)
        review = ComparisonReview(**values)
        append_review(review)
        return review

    return create


@pytest.fixture
def client():
    client = Client()
    client.force_login(User.objects.create_user("reader@example.com", "test-password"))
    return client


@pytest.fixture
def source():
    initialize_sources()
    return EvidenceSource.objects.get(pk="fed-monetary")


def entry(title="Original", published=None):
    return FeedEntry(
        "stable-guid",
        title,
        "Feed excerpt",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
        published,
    )


def test_news_revision_cutoff_and_return_to_prior_content(source):
    published = timezone.now() - timedelta(days=30)
    before = timezone.now()
    item = persist_entry(source, entry(published=published))
    original_cutoff = timezone.now()
    assert services.evidence_list(before, "", "", 0, 20).total == 0
    persist_entry(source, entry("Correction", published))
    correction_cutoff = timezone.now()
    persist_entry(source, entry(published=published))
    persist_entry(source, entry(published=published))
    assert item.revisions.count() == 3
    assert services.evidence_detail(item.id, original_cutoff).item.title == "Original"
    assert services.evidence_detail(item.id, correction_cutoff).item.title == "Correction"
    assert services.evidence_detail(item.id, None).item.version == 3
    assert item.first_observed_at > published
    with pytest.raises(ValidationError):
        item.revisions.first().save()


def test_unknown_publication_is_explicit_and_future_publication_is_hidden(source):
    item = persist_entry(source, entry())
    assert services.evidence_detail(item.id, None).item.published_at is None
    persist_entry(source, entry("Scheduled release", timezone.now() + timedelta(days=1)))
    assert services.evidence_list(None, "", "", 0, 20).total == 0


def test_associations_are_time_bounded_and_rejections_are_preserved(source, market):
    item = persist_entry(source, entry())
    before = timezone.now()
    associate_topics()
    associate_topics()
    assert EvidenceLink.objects.count() == 1
    assert services.timeline(market.id, before).items == []
    matched_cutoff = timezone.now()
    assert services.timeline(market.id, matched_cutoff).items[0].association.status == "TOPIC_ONLY"
    EvidenceLink.objects.create(
        item=item,
        market=market,
        status="REJECTED",
        method="operator-review-v1",
        rationale="Different meeting",
    )
    associate_topics()
    assert services.timeline(market.id, None).items == []
    assert services.timeline(market.id, matched_cutoff).items[0].association.status == "TOPIC_ONLY"
    assert services.evidence_detail(item.id, None).links[0].status == "REJECTED"


def test_source_polling_failure_keeps_evidence_and_does_not_leak_url(source):
    persist_entry(source, entry())
    with patch("quanthecy.research.news.fetch_feed", side_effect=OSError("secret-proxy-url")):
        assert poll_one_source()
    source.refresh_from_db()
    assert "OSError" in source.error
    assert "secret" not in source.error
    assert EvidenceRevision.objects.count() == 1
    assert source.next_poll_at > timezone.now() + timedelta(minutes=14)
    assert source.last_success_at is None


def test_conditional_fetch_success_and_pause(source, settings):
    EvidenceSource.objects.exclude(pk=source.pk).update(
        next_poll_at=timezone.now() + timedelta(days=1)
    )
    with patch(
        "quanthecy.research.news.fetch_feed", return_value=(None, "etag", "modified")
    ) as fetch:
        assert poll_one_source()
        assert not poll_one_source()
        assert fetch.call_count == 1
    source.refresh_from_db()
    assert source.last_success_at and source.etag == "etag"
    settings.NEWS_FEEDS_ENABLED = False
    EvidenceSource.objects.update(next_poll_at=timezone.now())
    assert not poll_one_source()


def test_feed_parser_restricts_links_and_rejects_entities():
    payload = (
        b"<rss><channel><item><title>Fed &amp; rates</title>"
        b"<link>https://www.federalreserve.gov/a.htm</link>"
        b"<description>&lt;b&gt;Statement&lt;/b&gt;</description>"
        b"<pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item>"
        b"<item><title>Unsafe</title><link>javascript:alert(1)</link></item></channel></rss>"
    )
    result = parse_feed(payload)
    assert len(result) == 1 and result[0].excerpt == "Statement"
    assert result[0].published_at.tzinfo is not None
    with pytest.raises(DefusedXmlException):
        parse_feed(
            b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel>&x;</channel></rss>'
        )
    with pytest.raises(ValueError):
        parse_feed(b"<html>Unavailable</html>")


def test_review_append_freezes_rules_and_history_visibility(pair, reviewer):
    before = timezone.now()
    review = reviewer()
    cutoff = timezone.now()
    assert services.comparisons(before) == []
    reviewer(relation="INCOMPATIBLE", rationale="Further rule review")
    assert services.comparisons(cutoff)[0].relation == "RELATED"
    assert services.comparisons(None)[0].version == 2
    pair.left.latest["market"]["resolution_rules"] = "Changed rules"
    pair.left.save()
    review.refresh_from_db()
    assert review.left_snapshot["market"]["resolution_rules"] != "Changed rules"
    with pytest.raises(ValidationError):
        review.save()
    with pytest.raises(ValidationError):
        reviewer(confidence=1.1)


def test_comparison_api_historical_inputs_and_failures(client, pair, reviewer):
    review = reviewer()
    repository = Mock(spec=ClickHouseRepository)
    repository.history.side_effect = lambda market, **kw: [
        pair.left.latest if market == pair.left_id else pair.right.latest
    ]
    with patch("quanthecy.research.services.history_repository", return_value=repository):
        response = client.get(f"/api/v1/comparisons/{pair.id}?hours=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["history"]) == 13
        assert data["current"]["difference"] is None
        assert "LEFT_STALE" in data["current"]["issues"]
        assert data["review"]["id"] == str(review.id)
        assert client.get(f"/api/v1/comparisons/{pair.id}?hours=25").status_code == 422
        assert client.get("/api/v1/comparisons?cutoff=2026-01-01").status_code == 422
        repository.history.side_effect = AnalyticsUnavailable("History unavailable")
        assert client.get(f"/api/v1/comparisons/{pair.id}").status_code == 503


def test_research_api_auth_and_operator_boundary(client, pair, reviewer, source):
    reviewer()
    item = persist_entry(source, entry())
    anonymous = Client()
    for path in (
        "research/overview",
        "comparisons",
        "evidence",
        f"evidence/{item.id}",
        "signals",
        f"markets/{pair.left_id}/timeline",
    ):
        assert anonymous.get(f"/api/v1/{path}").status_code == 401
    assert client.get("/api/v1/research/overview").json()["reviewed_pairs"] == 1
    assert client.get("/api/v1/evidence?limit=0").status_code == 422
    assert (
        client.post("/api/v1/comparisons", data={}, content_type="application/json").status_code
        == 405
    )
    assert client.get("/admin/research/comparisonreview/add/").status_code == 302


def test_manifest_is_idempotent_and_refuses_changed_current_rules(pair, reviewer, tmp_path):
    review = reviewer()
    row = dict(
        slug=pair.slug,
        title=review.title,
        relation=review.relation,
        alignment=review.alignment,
        confidence=review.confidence,
        rationale=review.rationale,
        differences=review.differences,
        reviewer_label=review.reviewer_label,
        left=dict(
            platform=pair.left.platform,
            exchange_id=pair.left.exchange_id,
            rules_version=review.left_snapshot["market"]["rules_version"],
        ),
        right=dict(
            platform=pair.right.platform,
            exchange_id=pair.right.exchange_id,
            rules_version=review.right_snapshot["market"]["rules_version"],
        ),
    )
    manifest = tmp_path / "review.json"
    manifest.write_text(json.dumps([row]))
    call_command("import_comparisons", str(manifest))
    assert pair.reviews.count() == 1
    pair.right.latest["market"]["rules_version"] = "changed"
    pair.right.save()
    with pytest.raises(CommandError, match="rules changed"):
        call_command("import_comparisons", str(manifest))


def test_operator_admin_creates_a_new_review_and_disallows_historical_edits(pair):
    client = Client()
    client.force_login(User.objects.create_superuser("operator@example.com", "test-password"))
    response = client.post(
        "/admin/research/comparisonreview/add/",
        {
            "comparison": str(pair.id),
            "title": "Reviewed Fed pair",
            "topic": "Macro & rates",
            "relation": "RELATED",
            "alignment": "SAME",
            "confidence": "0.9",
            "rationale": "Same meeting",
            "differences": "Different fallback rules",
            "reviewer_label": "Platform operator",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    review = ComparisonReview.objects.get()
    assert review.version == 1 and review.reviewed_by_id
    assert review.left_snapshot["market"]["id"] == str(pair.left_id)
    response = client.post(
        f"/admin/research/comparisonreview/{review.id}/change/", {"title": "Overwrite"}
    )
    assert response.status_code == 403


def test_comparison_refuses_truncated_inputs(client, pair, reviewer):
    reviewer()
    repository = Mock(spec=ClickHouseRepository)
    repository.history.return_value = [pair.left.latest] * 10001
    with patch("quanthecy.research.services.history_repository", return_value=repository):
        assert client.get(f"/api/v1/comparisons/{pair.id}").status_code == 422
