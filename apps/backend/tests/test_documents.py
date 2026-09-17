import hashlib
import json
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.agents.context import build_context
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import Market
from quanthecy.research import services
from quanthecy.research.documents import (
    MAX_BYTES,
    DocumentFailure,
    evidence_passages,
    extract_document,
    fetch_document,
    persist_document,
    poll_one_document,
    validate_url,
)
from quanthecy.research.feeds import FeedEntry, NoRedirects
from quanthecy.research.models import EvidenceItem, EvidenceLink, EvidenceSource
from quanthecy.research.news import persist_entry
from quanthecy_analytics.signals import analyze

pytestmark = pytest.mark.django_db
URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm"
BODY = "The committee discusses inflation and employment in this synthetic test paragraph. " * 3


def html(body=BODY, title="Test policy statement"):
    return (
        f'<html><div>Unrelated navigation</div><div id="article">'
        f'<div class="heading col-sm-8"><h3 class="title">{title}</h3>'
        "<p>Publication date and share navigation</p></div>"
        f'<div class="col-sm-8"><p>{body}</p><script>secret_script()</script>'
        "<p>Second paragraph with a policy qualification.</p></div></div>"
        "<footer>Unrelated footer</footer></html>"
    ).encode()


@pytest.fixture
def item():
    source = EvidenceSource.objects.create(
        slug="fed-monetary",
        name="Fed",
        url="https://www.federalreserve.gov/feeds/press_monetary.xml",
    )
    return persist_entry(
        source,
        FeedEntry(
            "example", "Fed statement", "RSS summary", URL, timezone.now() - timedelta(days=1)
        ),
    )


def collect(item, body=BODY):
    fetched = extract_document(item.source_id, URL, html(body))
    EvidenceItem.objects.filter(pk=item.pk).update(document_next_poll_at=timezone.now())
    with patch("quanthecy.research.documents.fetch_document", return_value=fetched):
        assert poll_one_document()
    item.refresh_from_db()
    return item.revisions.order_by("-version").first()


def test_article_extraction_excludes_navigation_scripts_and_preserves_provenance():
    raw = html()
    doc, saved = extract_document("fed-monetary", URL, raw)
    assert doc.title == "Test policy statement"
    assert doc.text == BODY.strip() + "\n\nSecond paragraph with a policy qualification."
    assert "navigation" not in doc.text and "secret_script" not in doc.text
    assert saved.encode() == raw and doc.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert doc.kind == "MONETARY_RELEASE" and doc.observed_at.tzinfo
    speech, _ = extract_document(
        "fed-speeches", "https://www.federalreserve.gov/newsevents/speech/waller20260903a.htm", raw
    )
    assert speech.kind == "SPEECH"


def test_nested_attachment_column_does_not_end_or_duplicate_article_body():
    body = (
        BODY
        + '<div class="panel panel-attachments col-sm-8"><div class="panel-body">'
        + '<a href="/attachment.pdf">Attachment (PDF)</a></div></div>'
        + "The qualification after the attachment is also part of the page."
    )
    doc, _ = extract_document("fed-monetary", URL, html(body))
    assert "Attachment (PDF)" in doc.text
    assert "qualification after the attachment" in doc.text
    assert "Second paragraph with a policy qualification." in doc.text
    assert "Unrelated footer" not in doc.text


@pytest.mark.parametrize(
    "url",
    [
        "http://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
        "https://www.federalreserve.gov.evil.test/newsevents/pressreleases/monetary20260729a.htm",
        "https://user@www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
        URL + "?next=http://127.0.0.1",
        URL + "#fragment",
        "https://www.federalreserve.gov:8443/newsevents/pressreleases/monetary20260729a.htm",
        "https://www.federalreserve.gov/newsevents/pressreleases/../private.htm",
        "https://127.0.0.1/internal",
    ],
)
def test_document_urls_are_source_specific_and_fail_before_network(url):
    with patch("quanthecy.research.documents.build_opener") as opener:
        with pytest.raises(DocumentFailure):
            fetch_document("fed-monetary", url)
        opener.assert_not_called()
    with pytest.raises(DocumentFailure):
        validate_url("fed-speeches", URL)


def test_unknown_layout_oversize_and_redirects_are_rejected():
    for raw in (
        b"<html><h3>Error</h3><p>Service unavailable</p></html>",
        b"x" * (MAX_BYTES + 1),
        html().split(b"</div></div>")[0],
    ):
        with pytest.raises(DocumentFailure):
            extract_document("fed-monetary", URL, raw)
    with pytest.raises(ValueError, match="redirect"):
        NoRedirects().redirect_request(None, None, 302, "", {}, "http://127.0.0.1")
    headers = Message()
    headers["Content-Type"] = "application/pdf"
    response = Mock(headers=headers)
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=response)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    with patch("quanthecy.research.documents.build_opener", return_value=opener):
        with pytest.raises(DocumentFailure, match="content_type"):
            fetch_document("fed-monetary", URL)
        response.read.assert_not_called()


def test_document_versions_are_immutable_deduplicated_and_cutoff_safe(item):
    before = timezone.now()
    first = collect(item)
    first_cutoff = timezone.now()
    assert first.version == 2 and item.document_last_success_at
    assert services.evidence_detail(item.pk, before).document is None
    assert services.evidence_detail(item.pk, first_cutoff).document.text.startswith(BODY.strip())
    assert services.evidence_detail(item.pk, before).document_collection is None
    collect(item)
    assert item.revisions.count() == 2
    second = collect(item, BODY + " The policy outlook has changed.")
    assert second.version == 3
    assert services.evidence_detail(item.pk, first_cutoff).item.version == 2
    assert "has changed" not in services.evidence_detail(item.pk, first_cutoff).document.text
    assert services.evidence_detail(item.pk, None).item.version == 3
    with pytest.raises(ValidationError):
        first.save()


def test_rss_refresh_does_not_erase_body_or_duplicate_versions(item):
    collect(item)
    latest = item.revisions.order_by("-version").first()
    entry = FeedEntry("example", latest.title, latest.excerpt, latest.url, latest.published_at)
    persist_entry(item.source, entry)
    assert item.revisions.count() == 2
    persist_entry(
        item.source,
        FeedEntry(
            "example", "Corrected RSS title", latest.excerpt, latest.url, latest.published_at
        ),
    )
    updated = item.revisions.order_by("-version").first()
    assert updated.version == 3 and updated.document == latest.document
    persist_entry(
        item.source,
        FeedEntry("example", "New URL", "Summary", URL.replace("29a", "29b"), latest.published_at),
    )
    assert item.revisions.order_by("-version").first().document == {}


def test_fetch_failure_retains_saved_evidence_and_retries_without_secrets(item):
    collect(item)
    EvidenceItem.objects.filter(pk=item.pk).update(document_next_poll_at=timezone.now())
    with patch(
        "quanthecy.research.documents.fetch_document", side_effect=OSError("secret-proxy-token")
    ) as fetch:
        assert poll_one_document()
        assert not poll_one_document()
        assert fetch.call_count == 1
    item.refresh_from_db()
    assert item.document_error == "document_fetch_failed" and item.document_failures == 1
    assert item.document_next_poll_at > timezone.now() + timedelta(minutes=14)
    assert item.revisions.count() == 2
    detail = services.evidence_detail(item.pk, None)
    assert detail.document and detail.document_collection.state == "retrying"


def test_disabled_future_and_leased_documents_do_not_fetch(item, settings):
    with patch("quanthecy.research.documents.fetch_document") as fetch:
        settings.NEWS_DOCUMENTS_ENABLED = False
        assert not poll_one_document()
        settings.NEWS_DOCUMENTS_ENABLED = True
        EvidenceItem.objects.filter(pk=item.pk).update(
            document_next_poll_at=timezone.now() + timedelta(minutes=5)
        )
        assert not poll_one_document()
        persist_entry(
            item.source,
            FeedEntry("example", "Future", "Scheduled", URL, timezone.now() + timedelta(days=1)),
        )
        assert not poll_one_document()
        fetch.assert_not_called()


def test_stale_fetch_lease_and_changed_source_url_do_not_publish(item):
    document, raw = extract_document(item.source_id, URL, html())
    lease = uuid4()
    EvidenceItem.objects.filter(pk=item.pk).update(document_lease=lease)
    assert not persist_document(item.pk, uuid4(), URL, document, raw)
    latest = item.revisions.first()
    persist_entry(
        item.source,
        FeedEntry("example", "Changed", "Summary", URL.replace("29a", "29b"), latest.published_at),
    )
    assert not persist_document(item.pk, lease, URL, document, raw)
    assert item.revisions.count() == 2
    assert not item.revisions.order_by("-version").first().document


def test_customer_api_uses_plain_text_and_never_returns_raw_html(item):
    collect(item)
    client = Client()
    assert client.get(f"/api/v1/evidence/{item.pk}").status_code == 401
    client.force_login(User.objects.create_user("doc-reader@example.com"))
    response = client.get(f"/api/v1/evidence/{item.pk}")
    assert response.status_code == 200
    data = response.json()
    assert data["document"]["text"].startswith(BODY.strip())
    assert data["item"]["document"]["character_count"] == len(data["document"]["text"])
    assert (
        "raw_document" not in response.content.decode()
        and "secret_script" not in response.content.decode()
    )


def test_api_version_timestamp_round_trips_without_losing_microseconds(item):
    observed = (timezone.now() - timedelta(seconds=1)).replace(microsecond=123456)
    saved = item.revisions.create(
        version=2,
        title="Revised official statement",
        excerpt="Version precision fixture",
        url=URL,
        published_at=observed - timedelta(days=1),
        observed_at=observed,
        content_hash="a" * 64,
    )
    client = Client()
    client.force_login(User.objects.create_user("version-reader@example.com"))
    detail = client.get(f"/api/v1/evidence/{item.pk}").json()
    cursor = detail["item"]["observed_at"]
    assert datetime.fromisoformat(cursor) == observed
    historical = client.get(f"/api/v1/evidence/{item.pk}", {"cutoff": cursor})
    assert historical.status_code == 200
    assert historical.json()["item"]["revision_id"] == str(saved.pk)


def test_agent_document_passages_use_exact_visible_revision_and_remain_bounded(item):
    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    market = Market.objects.get()
    EvidenceLink.objects.create(
        item=item, market=market, status="TOPIC_ONLY", rationale="Topic only"
    )
    before = timezone.now()
    revision = collect(item, BODY * 30)
    after = timezone.now()
    repo = Mock()
    repo.history.return_value = rows
    with patch("quanthecy.agents.context.history_repository", return_value=repo):
        old = build_context(market.pk, before)
        new = build_context(market.pk, after)
    old_ref = next(r for r in old["references"] if r["kind"] == "evidence")
    new_ref = next(r for r in new["references"] if r["kind"] == "evidence")
    assert "document_selection" not in old_ref["value"]
    assert new_ref["id"] == str(revision.id) and new["version"] == "context-v6"
    selection = new_ref["value"]["document_selection"]
    assert selection["partial"]
    assert sum(len(p["text"].encode()) for p in selection["passages"]) <= 1800
    assert new_ref["value"]["association"]["status"] == "TOPIC_ONLY"
    doc, _ = extract_document(item.source_id, URL, html("通胀政策" * 1000))
    assert sum(len(p["text"].encode()) for p in evidence_passages(doc)["passages"]) <= 1800


def test_document_response_cannot_publish_after_pause_or_frequency_edit(item):
    from quanthecy.accounts.models import User
    from quanthecy.research.source_controls import configure_source

    operator = User.objects.create_superuser("doc-control@example.com", "test")
    for enabled in (False, True):
        # Start a request, then change its source configuration before it returns.
        lease = uuid4()
        EvidenceItem.objects.filter(pk=item.pk).update(document_lease=lease)
        document, raw = extract_document(item.source_id, URL, html())
        configure_source(
            item.source_id, enabled=enabled, interval=600, reason="Update source", actor=operator
        )
        assert not persist_document(item.pk, lease, URL, document, raw)
        assert item.revisions.count() == 1
