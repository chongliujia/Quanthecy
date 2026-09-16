from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from quanthecy.markets.models import Market

from .feeds import SOURCES, FeedEntry, fetch_feed, parse_feed
from .models import EvidenceItem, EvidenceLink, EvidenceRevision, EvidenceSource


def initialize_sources() -> None:
    for slug, (name, url) in SOURCES.items():
        EvidenceSource.objects.get_or_create(slug=slug, defaults={"name": name, "url": url})


@transaction.atomic
def persist_entry(source: EvidenceSource, entry: FeedEntry) -> EvidenceItem:
    item, _ = EvidenceItem.objects.get_or_create(source=source, external_id=entry.external_id)
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
    item_ids = list(
        EvidenceItem.objects.filter(source_id__in=SOURCES)
        .order_by("-first_observed_at", "id")
        .values_list("id", flat=True)[:100]
    )
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
                            "Fed-topic wording in the market title and a Federal Reserve feed. "
                            "Topic relevance is unreviewed; timing does not establish causation."
                        ),
                    )
                    for item_id in item_ids
                    if item_id not in existing
                ]
            )


def poll_one_source() -> bool:
    if not settings.NEWS_FEEDS_ENABLED:
        return False
    with transaction.atomic():
        source = (
            EvidenceSource.objects.select_for_update(skip_locked=True)
            .filter(slug__in=SOURCES, next_poll_at__lte=timezone.now())
            .order_by("next_poll_at", "slug")
            .first()
        )
        if source is None:
            return False
        # Lease also enforces the polling limit across worker instances.
        source.next_poll_at = timezone.now() + timedelta(minutes=15)
        source.last_checked_at = timezone.now()
        source.save(update_fields=["next_poll_at", "last_checked_at"])
    try:
        data, etag, modified = fetch_feed(
            source.slug,
            etag=source.etag,
            last_modified=source.last_modified,
            proxy=settings.NEWS_PROXY_URL,
        )
        if data is not None:
            entries = parse_feed(data)
            for entry in entries:
                persist_entry(source, entry)
        EvidenceSource.objects.filter(pk=source.pk).update(
            last_success_at=timezone.now(),
            error="",
            etag=etag,
            last_modified=modified,
        )
    except Exception as exc:
        # No request URLs, proxy credentials or raw payloads enter error records.
        EvidenceSource.objects.filter(pk=source.pk).update(
            error=f"Feed refresh failed ({type(exc).__name__}); stored evidence retained."
        )
    return True
