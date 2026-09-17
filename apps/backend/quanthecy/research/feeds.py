"""Bounded RSS/Atom adapters. Article HTML is separately allowlisted in documents.py."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring

from .feed_registry import FEEDS

SOURCES = {slug: (spec.name, spec.url) for slug, spec in FEEDS.items()}
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 100
ATOM = "{http://www.w3.org/2005/Atom}"


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain(value: str, limit: int) -> str:
    parser = PlainText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())[:limit]


@dataclass(frozen=True)
class FeedEntry:
    external_id: str
    title: str
    excerpt: str
    url: str
    published_at: datetime | None
    raw_fields: dict[str, str] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        value = [
            self.title,
            self.excerpt,
            self.url,
            self.published_at.isoformat() if self.published_at else None,
        ]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


@dataclass
class ParsedFeed:
    entries: list[FeedEntry] = field(default_factory=list)
    total: int = 0
    rejected: int = 0
    duplicates: int = 0
    undated: int = 0
    truncated: bool = False


def canonical_url(url: str, slug: str) -> str:
    """Validate article links without fetching them; discard known tracking fields only."""
    try:
        target = urlsplit(url.strip())
        if (
            target.scheme != "https"
            or target.hostname not in FEEDS[slug].article_hosts
            or target.username
            or target.password
            or target.port not in (None, 443)
            or len(url) > 2000
            or any(ord(c) < 32 for c in url)
            or "\\" in url
        ):
            return ""
        query = [
            (key, value)
            for key, value in parse_qsl(target.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"at_medium", "at_campaign", "fbclid", "gclid"}
        ]
        return urlunsplit(("https", target.hostname, target.path or "/", urlencode(query), ""))
    except (ValueError, KeyError):
        return ""


def publication_time(raw: str) -> datetime | None:
    for parser in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            value = parser(raw.strip().replace("Z", "+00:00"))
            if value.tzinfo is not None:
                return value.astimezone(UTC)
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def node_text(node: Element, path: str) -> str:
    found = node.find(path)
    return "" if found is None else "".join(found.itertext())


def parse_feed_result(
    data: bytes, slug: str = "fed-monetary", *, now: datetime | None = None
) -> ParsedFeed:
    if len(data) > MAX_BYTES:
        raise ValueError("Feed exceeds size limit")
    root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    atom = root.tag == f"{ATOM}feed"
    if atom:
        nodes = root.findall(f"{ATOM}entry")
    elif root.tag == "rss" and root.find("channel") is not None:
        nodes = root.findall("./channel/item")
    else:
        raise ValueError("Expected RSS 2.0 or Atom feed")
    result = ParsedFeed(total=len(nodes), truncated=len(nodes) > MAX_ITEMS)
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    now = now or datetime.now(UTC)
    for node in nodes[:MAX_ITEMS]:
        prefix = ATOM if atom else ""
        raw_url = node.findtext("link") or ""
        if atom:
            raw_url = next(
                (
                    n.get("href", "")
                    for n in node.findall(f"{ATOM}link")
                    if n.get("rel", "alternate") == "alternate"
                ),
                "",
            )
        url = canonical_url(raw_url, slug)
        raw_title = node_text(node, f"{prefix}title")
        raw_excerpt = node_text(node, f"{prefix}{'summary' if atom else 'description'}")
        raw_date = node.findtext(f"{prefix}{'published' if atom else 'pubDate'}") or ""
        # Atom updated is a modification timestamp, never a substitute publication date.
        identity = (node.findtext(f"{prefix}{'id' if atom else 'guid'}") or url).strip()
        title = plain(raw_title, 1000)
        published = publication_time(raw_date)
        if (
            not url
            or not title
            or not identity
            or len(identity) > 1000
            or (published is not None and published > now)
        ):
            result.rejected += 1
            continue
        if identity in seen_ids or url in seen_urls:
            result.duplicates += 1
            continue
        seen_ids.add(identity)
        seen_urls.add(url)
        result.undated += int(published is None)
        result.entries.append(
            FeedEntry(
                identity,
                title,
                plain(raw_excerpt, 4000),
                url,
                published,
                {
                    "title": raw_title[:1000],
                    "description": raw_excerpt[:4000],
                    "link": raw_url[:2000],
                    "identity": identity,
                    "publication": raw_date[:200],
                    "updated": (node.findtext(f"{ATOM}updated") or "")[:200],
                    "format": "atom" if atom else "rss",
                },
            )
        )
    return result


def parse_feed(data: bytes, slug: str = "fed-monetary") -> list[FeedEntry]:
    return parse_feed_result(data, slug).entries


class NoRedirects(HTTPRedirectHandler):
    # A registry URL cannot redirect the worker into a private network.
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        raise ValueError("Feed redirect refused")


def fetch_feed(
    slug: str, *, etag: str, last_modified: str, proxy: str
) -> tuple[bytes | None, str, str]:
    headers = {
        "User-Agent": "Quanthecy/0.1 (public research feed reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    opener = build_opener(NoRedirects(), ProxyHandler({"https": proxy} if proxy else {}))
    try:
        with opener.open(Request(SOURCES[slug][1], headers=headers), timeout=10) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Feed exceeds size limit")
            return (
                data,
                response.headers.get("ETag", "")[:500],
                response.headers.get("Last-Modified", "")[:200],
            )
    except HTTPError as exc:
        if exc.code == 304:
            return None, etag, last_modified
        raise
