from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.operations.models import PlatformAuditLog
from quanthecy.research.documents import poll_one_document
from quanthecy.research.feeds import FeedEntry, canonical_url, parse_feed_result
from quanthecy.research.models import EvidenceItem, EvidenceLink, EvidenceRevision, EvidenceSource
from quanthecy.research.news import (
    associate_topics,
    initialize_sources,
    persist_entry,
    poll_one_source,
)
from quanthecy.research.services import evidence_detail, source_value
from quanthecy.research.source_controls import configure_source

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 1, 2, tzinfo=UTC)
URL = "https://www.bbc.co.uk/news/articles/example"


def rss(*items):
    return ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()


def item(
    guid="id-1", url=URL, title="Federal Reserve holds rates", date="Thu, 01 Jan 2026 12:00:00 GMT"
):
    return (
        f"<item><guid>{guid}</guid><title>{title}</title>"
        f"<link>{url}</link><pubDate>{date}</pubDate></item>"
    )


@pytest.fixture
def source():
    initialize_sources()
    EvidenceSource.objects.update(next_poll_at=timezone.now() + timedelta(days=1))
    source = EvidenceSource.objects.get(pk="bbc-business")
    source.next_poll_at = timezone.now()
    source.save()
    return source


def test_parser_deduplicates_tracking_urls_and_retains_raw_fields():
    parsed = parse_feed_result(
        rss(item(url=URL + "?utm_source=rss"), item(guid="new-guid", url=URL + "#top")),
        "bbc-business",
        now=NOW,
    )
    assert parsed.total == 2 and parsed.duplicates == 1
    assert parsed.entries[0].url == URL
    assert parsed.entries[0].raw_fields["link"].endswith("?utm_source=rss")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bbc.co.uk:bad/a",
        "https://www.bbc.co.uk@127.0.0.1/a",
        "https://www.bbc.co.uk.evil.test/a",
        "http://www.bbc.co.uk/a",
        "https://user:password@www.bbc.co.uk/a",
        "https://127.0.0.1/a",
        "javascript:alert(1)",
        "https://www.bbc.co.uk\\@evil.test/a",
    ],
)
def test_rejects_unsafe_links_without_poisoning_the_feed(url):
    parsed = parse_feed_result(rss(item(url=url), item(guid="good")), "bbc-business", now=NOW)
    assert len(parsed.entries) == 1 and parsed.rejected == 1
    assert canonical_url(url, "bbc-business") == ""


def test_atom_does_not_treat_updated_as_publication():
    data = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>one</id><title>Economic release</title>
      <link rel="self" href="https://bad.test/self"/>
      <link href="https://www.bea.gov/news/2026/release"/>
      <updated>2026-01-01T12:00:00Z</updated><summary>Summary</summary>
    </entry></feed>"""
    parsed = parse_feed_result(data, "bea-releases", now=NOW)
    assert parsed.undated == 1
    assert parsed.entries[0].published_at is None
    assert parsed.entries[0].raw_fields["updated"] == "2026-01-01T12:00:00Z"


def test_future_dates_rejected_and_missing_dates_explicit():
    parsed = parse_feed_result(
        rss(
            item(guid="future", date="Sat, 03 Jan 2026 12:00:00 GMT"),
            item(guid="missing", date=""),
        ),
        "bbc-business",
        now=NOW,
    )
    assert parsed.rejected == 1 and parsed.undated == 1
    assert parsed.entries[0].published_at is None


def test_changed_guid_reuses_item_and_changed_content_appends_revision(source):
    original = parse_feed_result(rss(item()), "bbc-business", now=NOW).entries[0]
    saved = persist_entry(source, original)
    changed = parse_feed_result(
        rss(item(guid="changed", title="Correction")), "bbc-business", now=NOW
    ).entries[0]
    assert persist_entry(source, changed).pk == saved.pk
    persist_entry(source, changed)
    assert EvidenceItem.objects.count() == 1
    assert saved.revisions.count() == 2
    assert saved.revisions.get(version=1).raw_feed_fields["title"] == original.title


def test_media_provenance_and_no_document_crawl(source):
    saved = persist_entry(source, FeedEntry("one", "Fed report", "Excerpt", URL, NOW))
    detail = evidence_detail(saved.pk, None)
    assert detail.item.source_kind == "MEDIA"
    assert detail.document_collection.state == "unsupported"
    assert not detail.item.document_supported
    with patch("quanthecy.research.documents.fetch_document") as fetch:
        assert not poll_one_document()
        fetch.assert_not_called()
    assert evidence_detail(saved.pk, timezone.now()).document_collection is None


def test_pause_and_initialization_preserve_operator_choices(source):
    source.enabled = False
    source.poll_interval_seconds = 600
    source.save()
    initialize_sources()
    source.refresh_from_db()
    assert not source.enabled and source.poll_interval_seconds == 600
    with patch("quanthecy.research.news.fetch_feed") as fetch:
        assert not poll_one_source()
        fetch.assert_not_called()
    assert source_value(source).status == "paused"


def test_empty_partial_and_unchanged_are_not_falsely_healthy(source):
    with patch("quanthecy.research.news.fetch_feed", return_value=(rss(item(date="")), "e1", "")):
        assert poll_one_source()
    source.refresh_from_db()
    assert source.last_undated_count == 1 and source_value(source).status == "partial"
    EvidenceSource.objects.filter(pk=source.pk).update(next_poll_at=timezone.now())
    with patch("quanthecy.research.news.fetch_feed", return_value=(None, "e1", "")):
        assert poll_one_source()
    source.refresh_from_db()
    assert source_value(source).status == "partial"
    EvidenceSource.objects.filter(pk=source.pk).update(next_poll_at=timezone.now())
    with patch("quanthecy.research.news.fetch_feed", return_value=(rss(), "empty", "")):
        assert poll_one_source()
    source.refresh_from_db()
    assert source_value(source).status == "empty"
    assert source.etag == "" and EvidenceItem.objects.count() == 1


def test_retry_after_and_recovery(source):
    failure = HTTPError("https://secret.invalid", 429, "limited", {"Retry-After": "7200"}, None)
    with patch("quanthecy.research.news.fetch_feed", side_effect=failure):
        poll_one_source()
    source.refresh_from_db()
    assert source.consecutive_failures == 1 and "HTTP 429" in source.error
    assert "secret" not in source.error
    assert source.next_poll_at > timezone.now() + timedelta(seconds=7100)
    EvidenceSource.objects.filter(pk=source.pk).update(next_poll_at=timezone.now())
    with patch("quanthecy.research.news.fetch_feed", return_value=(rss(item()), "ok", "")):
        poll_one_source()
    source.refresh_from_db()
    assert source_value(source).status == "healthy"
    assert source.consecutive_failures == 0 and source.error == ""


def test_truncated_feed_is_refetched_after_failure(source):
    data = rss(*(item(guid=str(i), url=f"{URL}/{i}") for i in range(101)))
    with patch("quanthecy.research.news.fetch_feed", return_value=(data, "e1", "date")):
        poll_one_source()
    source.refresh_from_db()
    assert source.last_entry_count == 100 and source_value(source).status == "partial"
    EvidenceSource.objects.filter(pk=source.pk).update(next_poll_at=timezone.now())
    with patch("quanthecy.research.news.fetch_feed", side_effect=TimeoutError):
        poll_one_source()
    source.refresh_from_db()
    assert source.etag == source.last_modified == ""
    EvidenceSource.objects.filter(pk=source.pk).update(next_poll_at=timezone.now())
    with patch("quanthecy.research.news.fetch_feed", return_value=(data, "e1", "date")) as fetch:
        poll_one_source()
    assert fetch.call_args.kwargs["etag"] == fetch.call_args.kwargs["last_modified"] == ""
    source.refresh_from_db()
    assert source_value(source).status == "partial"


def test_worker_cannot_publish_after_operator_pause(source):
    operator = User.objects.create_superuser("operator@example.com", "test")

    def response(*args, **kwargs):
        configure_source(
            source.pk, enabled=False, interval=900, reason="Pause feed", actor=operator
        )
        return rss(item()), "etag", ""

    with patch("quanthecy.research.news.fetch_feed", side_effect=response):
        assert poll_one_source()
    assert not EvidenceRevision.objects.exists()
    assert PlatformAuditLog.objects.get().details["source_slug"] == source.pk
    assert PlatformAuditLog.objects.get().details["after"]["enabled"] is False


def test_source_api_and_admin_permission_boundary(source):
    reader = User.objects.create_user("reader@example.com", "test")
    client = Client()
    assert client.get("/api/v1/research/sources").status_code == 401
    client.force_login(reader)
    data = client.get("/api/v1/research/sources").json()
    assert len(data["sources"]) == 8
    assert next(s for s in data["sources"] if s["slug"] == source.pk)["kind"] == "MEDIA"
    with pytest.raises(PermissionDenied):
        configure_source(source.pk, enabled=False, interval=900, reason="Pause", actor=reader)
    client.force_login(User.objects.create_superuser("admin@example.com", "test"))
    path = f"/admin/research/evidencesource/{source.pk}/change/"
    assert (
        client.post(
            path, {"enabled": "on", "poll_interval_seconds": 1, "change_reason": "Too fast"}
        ).status_code
        == 200
    )
    assert not PlatformAuditLog.objects.exists()
    assert (
        client.post(
            path, {"poll_interval_seconds": 600, "change_reason": "Pause source", "_save": "Save"}
        ).status_code
        == 302
    )
    source.refresh_from_db()
    assert not source.enabled and source.poll_interval_seconds == 600
    assert client.get(f"/admin/research/evidencesource/{source.pk}/delete/").status_code == 403


def test_source_type_filter_does_not_upgrade_media(source):
    client = Client()
    client.force_login(User.objects.create_user("reader@example.com", "test"))
    persist_entry(source, FeedEntry("news", "Fed report", "Excerpt", URL, NOW))
    assert client.get("/api/v1/evidence?kind=OFFICIAL").json()["total"] == 0
    assert client.get("/api/v1/evidence?kind=MEDIA").json()["total"] == 1
    assert client.get("/api/v1/evidence?kind=UNKNOWN").status_code == 422


def test_unrelated_business_news_not_associated(source):
    import json
    from pathlib import Path

    from django.db import transaction
    from quanthecy.markets.ingestion import reconcile
    from quanthecy.markets.models import Market
    from quanthecy_analytics.signals import analyze

    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )
    with transaction.atomic():
        reconcile(rows[-1], analyze(rows)[0])
    market = Market.objects.get()
    market.title = "Federal Reserve decision?"
    market.save()
    relevant = persist_entry(source, FeedEntry("fed", "Federal Reserve decision", "", URL, NOW))
    persist_entry(source, FeedEntry("other", "New phone launch", "Technology", URL + "-other", NOW))
    associate_topics()
    assert list(EvidenceLink.objects.filter(market=market).values_list("item_id", flat=True)) == [
        relevant.pk
    ]
    assert EvidenceLink.objects.get().status == "TOPIC_ONLY"


def test_upgraded_source_refreshes_counters_instead_of_accepting_304(source):
    source.etag = "old-etag"
    source.last_modified = "old-date"
    source.last_success_at = timezone.now()
    source.save()
    with patch(
        "quanthecy.research.news.fetch_feed", return_value=(rss(item()), "new-etag", "")
    ) as fetch:
        poll_one_source()
    assert fetch.call_args.kwargs["etag"] == fetch.call_args.kwargs["last_modified"] == ""
    source.refresh_from_db()
    assert source.last_entry_count == 1
