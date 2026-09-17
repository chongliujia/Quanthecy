import re
from datetime import timedelta
from urllib.error import HTTPError
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from quanthecy.markets.models import Market

from .feed_registry import FEEDS
from .feeds import FeedEntry, fetch_feed, parse_feed_result, publication_time
from .models import EvidenceItem, EvidenceLink, EvidenceRevision, EvidenceSource


def initialize_sources() -> None:
    for slug, spec in FEEDS.items():
        EvidenceSource.objects.get_or_create(
            slug=slug, defaults={"name": spec.name, "url": spec.url, "enabled": spec.enabled}
        )


@transaction.atomic
def persist_entry(source: EvidenceSource, entry: FeedEntry) -> EvidenceItem:
    # Serialize alternate GUIDs for the same publisher URL, including concurrent workers.
    EvidenceSource.objects.select_for_update().get(pk=source.pk)
    item = EvidenceItem.objects.filter(source=source, external_id=entry.external_id).first()
    if item is None:
        item = (
            EvidenceItem.objects.filter(source=source, revisions__url=entry.url)
            .order_by("first_observed_at", "id")
            .first()
        )
    if item is None:
        item = EvidenceItem.objects.create(source=source, external_id=entry.external_id)
    item = EvidenceItem.objects.select_for_update().get(pk=item.pk)
    previous = item.revisions.order_by("-version").first()
    fields = ("title", "excerpt", "url", "published_at")
    if previous is None or any(getattr(previous, key) != getattr(entry, key) for key in fields):
        from .documents import revision_hash

        document = previous.document if previous and previous.url == entry.url else {}
        raw_document = previous.raw_document if document and previous else ""
        values = {key: getattr(entry, key) for key in fields}
        EvidenceRevision.objects.create(
            item=item,
            version=previous.version + 1 if previous else 1,
            title=entry.title,
            excerpt=entry.excerpt,
            url=entry.url,
            published_at=entry.published_at,
            content_hash=revision_hash({**values, "document": document})
            if document
            else entry.content_hash,
            document=document,
            raw_document=raw_document,
            raw_feed_fields=entry.raw_fields,
        )
        item.document_next_poll_at = timezone.now()
        item.save(update_fields=["document_next_poll_at"])
    return item


def associate_topics() -> None:
    # Bound both dimensions. Re-run for new markets even when feeds return 304.
    markets = Market.objects.filter(
        Q(title__icontains="fed ")
        | Q(title__icontains="federal reserve")
        | Q(title__icontains="fomc")
    ).order_by("id")[:100]
    from .services import visible_evidence

    # Broad business feeds contain unrelated stories. Only explicit US macro wording
    # becomes a candidate; these associations never grant event-level approval.
    macro_wording = re.compile(
        r"\b(?:federal reserve|fomc|fed|u\.?s\.?\s+(?:inflation|employment|economy))\b",
        re.IGNORECASE,
    )
    candidates = (
        visible_evidence(timezone.now())
        .filter(item__source_id__in=FEEDS)
        .order_by("-observed_at", "id")[:500]
    )
    item_ids = [
        r.item_id
        for r in candidates
        if r.item.source_id.startswith("fed-")
        or r.item.source_id.startswith("bls-")
        or r.item.source_id == "bea-releases"
        or macro_wording.search(f"{r.title} {r.excerpt}")
    ][:100]
    for market in markets:
        # Serialize automatic association with manual review on the market row.
        with transaction.atomic():
            Market.objects.select_for_update().get(pk=market.pk)
            existing = set(
                EvidenceLink.objects.filter(market=market, item_id__in=item_ids).values_list(
                    "item_id", flat=True
                )
            )
            EvidenceLink.objects.bulk_create(
                [
                    EvidenceLink(
                        item_id=item_id,
                        market=market,
                        rationale=(
                            "Fed-topic market and a US macro source or explicit US macro wording. "
                            "Unreviewed background candidate; not evidence for a particular "
                            "meeting or outcome. Timing does not establish causation."
                        ),
                        method="macro-topic-v2",
                    )
                    for item_id in item_ids
                    if item_id not in existing
                ]
            )


def poll_one_source() -> bool:
    if not settings.NEWS_FEEDS_ENABLED:
        return False
    now = timezone.now()
    lease = uuid4()
    with transaction.atomic():
        source = (
            EvidenceSource.objects.select_for_update(skip_locked=True)
            .filter(slug__in=FEEDS, enabled=True, next_poll_at__lte=now)
            .filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
            .order_by("next_poll_at", "slug")
            .first()
        )
        if source is None:
            return False
        # Lease also enforces the polling limit across worker instances.
        source.next_poll_at = now + timedelta(seconds=source.poll_interval_seconds)
        source.last_checked_at = now
        source.poll_lease = lease
        source.lease_expires_at = now + timedelta(minutes=2)
        source.save(
            update_fields=["next_poll_at", "last_checked_at", "poll_lease", "lease_expires_at"]
        )
    try:
        data, etag, modified = fetch_feed(
            source.slug,
            # Existing sources upgraded before counters existed need one full body.
            etag=source.etag if source.last_entry_count else "",
            last_modified=source.last_modified if source.last_entry_count else "",
            proxy=settings.NEWS_PROXY_URL,
        )
        parsed = parse_feed_result(data, source.slug) if data is not None else None
        with transaction.atomic():
            current = EvidenceSource.objects.select_for_update().get(pk=source.pk)
            if current.poll_lease != lease or not current.enabled:
                return True
            if parsed is not None:
                for entry in parsed.entries:
                    persist_entry(current, entry)
                current.last_entry_count = len(parsed.entries)
                current.last_rejected_count = parsed.rejected
                current.last_duplicate_count = parsed.duplicates
                current.last_undated_count = parsed.undated
                current.last_result = (
                    "empty"
                    if not parsed.entries
                    else "partial"
                    if parsed.rejected or parsed.undated or parsed.truncated
                    else "updated"
                )
                dates = [e.published_at for e in parsed.entries if e.published_at is not None]
                if dates:
                    current.latest_published_at = max(dates)
            elif current.last_result == "failed" and current.last_success_at:
                current.last_result = (
                    "empty"
                    if not current.last_entry_count
                    else "partial"
                    if current.last_rejected_count or current.last_undated_count
                    else "unchanged"
                )
            elif current.last_result not in {"empty", "partial"}:
                current.last_result = "unchanged"
            current.last_success_at = timezone.now()
            current.error = ""
            current.consecutive_failures = 0
            # An all-rejected response must be reparsed on the next request (e.g.
            # future timestamps); do not freeze it behind a conditional 304.
            current.etag = "" if parsed and not parsed.entries else etag
            current.last_modified = "" if parsed and not parsed.entries else modified
            current.poll_lease = None
            current.lease_expires_at = None
            current.save()
    except Exception as exc:
        # No request URLs, proxy credentials or raw payloads enter error records.
        failures = min(source.consecutive_failures + 1, 10)
        delay = min(source.poll_interval_seconds * 2 ** (failures - 1), 21600)
        code = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        if isinstance(exc, HTTPError) and exc.code in {429, 503}:
            retry = exc.headers.get("Retry-After", "") if exc.headers else ""
            if retry.isdigit():
                delay = max(delay, min(int(retry), 86400))
            elif at := publication_time(retry):
                delay = max(delay, min(int((at - timezone.now()).total_seconds()), 86400))
        EvidenceSource.objects.filter(pk=source.pk, poll_lease=lease, enabled=True).update(
            error=f"Feed refresh failed ({code}); stored evidence retained.",
            consecutive_failures=failures,
            last_result="failed",
            # Re-evaluate all quality flags after recovery, including truncation,
            # which cannot be reconstructed from stored entry counts after a 304.
            etag="",
            last_modified="",
            next_poll_at=timezone.now() + timedelta(seconds=delay),
            poll_lease=None,
            lease_expires_at=None,
        )
    return True
