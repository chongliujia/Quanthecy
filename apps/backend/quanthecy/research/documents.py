"""Bounded, source-specific official documents; never crawl links or run page code."""

import hashlib
import json
import re
from datetime import timedelta
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .feeds import NoRedirects
from .models import EvidenceItem, EvidenceRevision

EXTRACTOR = "fed-article-v1"
MAX_BYTES = 1024 * 1024
MAX_TEXT = 120_000
PATHS = {
    "fed-monetary": r"/newsevents/pressreleases/monetary[0-9]{8}[a-z][0-9]?\.htm",
    "fed-speeches": r"/newsevents/speech/[a-z]+[0-9]{8}[a-z]\.htm",
}


class OfficialDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extractor_version: Literal["fed-article-v1"] = "fed-article-v1"
    url: str
    title: str = Field(min_length=1, max_length=1000)
    kind: Literal["MONETARY_RELEASE", "SPEECH"]
    text: str = Field(min_length=100, max_length=MAX_TEXT)
    observed_at: AwareDatetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentFailure(Exception):
    """Only fixed codes are stored; URLs and exception text are never diagnostics."""


def validate_url(source: str, url: str) -> None:
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or target.netloc != "www.federalreserve.gov"
        or target.query
        or target.fragment
        or source not in PATHS
        or not re.fullmatch(PATHS[source], target.path)
    ):
        raise DocumentFailure("unsupported_document_url")


class FedArticle(HTMLParser):
    """Recognize the Fed's article/body columns; reject layout changes explicitly."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.article = 0
        self.body = 0
        self.body_count = 0
        self.in_title = False
        self.ignored: str | None = None
        self.parts: list[str] = []
        self.title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self.ignored = tag
        if tag == "div":
            self.depth += 1
            if values.get("id") == "article":
                self.article = self.depth
            classes = (values.get("class") or "").split()
            if (
                self.article
                and not self.body
                and "col-sm-8" in classes
                and "heading" not in classes
            ):
                self.body = self.depth
                self.body_count += 1
        if self.article and tag == "h3" and "title" in (values.get("class") or "").split():
            self.in_title = True
        if self.body and tag in {"p", "h2", "h3", "h4", "li", "br", "tr"}:
            self.parts.append("\n\n")
        if self.body and tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.ignored:
            self.ignored = None
        if tag == "h3":
            self.in_title = False
        if self.body and tag in {"p", "h2", "h3", "h4", "li", "tr"}:
            self.parts.append("\n\n")
        if tag == "div":
            if self.depth == self.body:
                self.body = 0
            if self.depth == self.article:
                self.article = 0
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.ignored:
            return
        if self.body:
            self.parts.append(data)
        if self.in_title:
            self.title.append(data)


def extract_document(source: str, url: str, raw: bytes) -> tuple[OfficialDocument, str]:
    validate_url(source, url)
    if len(raw) > MAX_BYTES:
        raise DocumentFailure("document_too_large")
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentFailure("unsupported_encoding") from None
    parser = FedArticle()
    parser.feed(html)
    parser.close()
    title = " ".join("".join(parser.title).split())
    paragraphs = [" ".join(part.split()) for part in "".join(parser.parts).split("\n\n")]
    text = "\n\n".join(part for part in paragraphs if part)
    if (
        parser.body_count != 1
        or parser.body
        or parser.article
        or not title
        or not 100 <= len(text) <= MAX_TEXT
    ):
        raise DocumentFailure("unrecognized_document_layout")
    return OfficialDocument(
        url=url,
        title=title,
        kind="SPEECH" if source == "fed-speeches" else "MONETARY_RELEASE",
        text=text,
        observed_at=timezone.now(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    ), html


def fetch_document(source: str, url: str) -> tuple[OfficialDocument, str]:
    validate_url(source, url)
    opener = build_opener(
        NoRedirects(),
        ProxyHandler({"https": settings.NEWS_PROXY_URL} if settings.NEWS_PROXY_URL else {}),
    )
    request = Request(
        url,
        headers={
            "User-Agent": "Quanthecy/0.1 (official public evidence reader)",
            "Accept": "text/html",
        },
    )
    with opener.open(request, timeout=10) as response:
        if response.headers.get_content_type() != "text/html":
            raise DocumentFailure("unsupported_content_type")
        raw = response.read(MAX_BYTES + 1)
    return extract_document(source, url, raw)


def revision_hash(values: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


@transaction.atomic
def persist_document(
    item_id: UUID, lease: UUID, expected_url: str, document: OfficialDocument, raw: str
) -> bool:
    # Match feed/configuration lock ordering: source, then item.
    from .models import EvidenceSource

    source_id = EvidenceItem.objects.values_list("source_id", flat=True).get(pk=item_id)
    source = EvidenceSource.objects.select_for_update().get(pk=source_id)
    item = EvidenceItem.objects.select_for_update().get(pk=item_id)
    if not source.enabled:
        return False
    if item.document_lease != lease:
        return False
    previous = item.revisions.order_by("-version").first()
    if previous is None or previous.url != expected_url or document.url != expected_url:
        # An RSS revision changed the target while this request was in flight.
        item.document_next_poll_at = timezone.now()
        item.document_lease = None
        item.save(update_fields=["document_next_poll_at", "document_lease"])
        return False
    validate_url(item.source_id, document.url)
    if document.observed_at > timezone.now():
        raise DocumentFailure("future_document_time")
    old = previous.document
    identity = ("text_sha256", "title", "kind", "url", "extractor_version")
    saved = document.model_dump(mode="json")
    if not old or any(old.get(key) != saved[key] for key in identity):
        values = {
            name: getattr(previous, name) for name in ("title", "excerpt", "url", "published_at")
        }
        EvidenceRevision.objects.create(
            item=item,
            version=previous.version + 1,
            **values,
            document=saved,
            raw_document=raw,
            raw_feed_fields=previous.raw_feed_fields,
            content_hash=revision_hash({**values, "document": saved}),
        )
    # Navigation/HTML churn with identical extracted content does not create revisions.
    now = timezone.now()
    item.document_last_success_at = now
    item.document_next_poll_at = now + timedelta(hours=24)
    item.document_error = ""
    item.document_failures = 0
    item.document_lease = None
    item.save(
        update_fields=[
            "document_last_success_at",
            "document_next_poll_at",
            "document_error",
            "document_failures",
            "document_lease",
        ]
    )
    return True


def poll_one_document() -> bool:
    if not settings.NEWS_FEEDS_ENABLED or not settings.NEWS_DOCUMENTS_ENABLED:
        return False
    now = timezone.now()
    latest = EvidenceRevision.objects.filter(item_id=OuterRef("pk")).order_by("-version")
    with transaction.atomic():
        item = (
            EvidenceItem.objects.select_for_update(skip_locked=True)
            .filter(source_id__in=PATHS, source__enabled=True, document_next_poll_at__lte=now)
            .annotate(publication=Subquery(latest.values("published_at")[:1]))
            .filter(publication__lte=now)
            .order_by("document_next_poll_at", "-publication", "id")
            .first()
        )
        if item is None:
            return False
        previous = item.revisions.order_by("-version").first()
        assert previous is not None
        url = previous.url
        lease = uuid4()
        item.document_lease = lease
        item.document_last_checked_at = now
        item.document_next_poll_at = now + timedelta(minutes=5)
        item.save(
            update_fields=["document_lease", "document_last_checked_at", "document_next_poll_at"]
        )
    try:
        document, raw = fetch_document(item.source_id, url)
        persist_document(item.pk, lease, url, document, raw)
    except Exception as exc:
        code = str(exc) if isinstance(exc, DocumentFailure) else "document_fetch_failed"
        failures = min(item.document_failures + 1, 10)
        EvidenceItem.objects.filter(pk=item.pk, document_lease=lease).update(
            document_error=code,
            document_failures=failures,
            document_next_poll_at=timezone.now()
            + timedelta(minutes=min(15 * 2 ** (failures - 1), 1440)),
            document_lease=None,
        )
    return True


def evidence_passages(document: OfficialDocument, budget: int = 1800) -> dict[str, object]:
    """Deterministic excerpts, with paragraph identity and explicit byte-budget omissions."""
    paragraphs = document.text.split("\n\n")
    terms = ("federal funds", "policy rate", "fomc", "inflation", "employment", "target range")
    ranked = sorted(
        range(len(paragraphs)),
        key=lambda i: (-sum(term in paragraphs[i].lower() for term in terms), i),
    )
    chosen: list[dict[str, object]] = []
    for index in ranked[:3]:
        remaining = budget - sum(len(str(p["text"]).encode()) for p in chosen)
        if remaining < 100:
            break
        original = paragraphs[index]
        text = original.encode()[: min(1000, remaining)].decode("utf-8", errors="ignore")
        chosen.append({"paragraph": index + 1, "text": text, "truncated": text != original})
    return {
        "selection": "fed-policy-terms-v1",
        "paragraph_count": len(paragraphs),
        "passages": sorted(chosen, key=lambda p: int(str(p["paragraph"]))),
        "partial": len(chosen) < len(paragraphs) or any(p["truncated"] for p in chosen),
    }
