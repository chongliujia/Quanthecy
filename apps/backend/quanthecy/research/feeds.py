"""Restricted RSS adapters. Official HTML retrieval is separately allowlisted in documents.py."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from defusedxml.ElementTree import fromstring

SOURCES = {
    "fed-monetary": (
        "Federal Reserve · Monetary policy",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
    ),
    "fed-speeches": (
        "Federal Reserve · Speeches",
        "https://www.federalreserve.gov/feeds/speeches.xml",
    ),
}
MAX_BYTES = 2 * 1024 * 1024


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

    @property
    def content_hash(self) -> str:
        value = [
            self.title,
            self.excerpt,
            self.url,
            self.published_at.isoformat() if self.published_at else None,
        ]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def parse_feed(data: bytes) -> list[FeedEntry]:
    if len(data) > MAX_BYTES:
        raise ValueError("Feed exceeds size limit")
    root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected RSS 2.0 feed")
    entries = []
    seen: set[str] = set()
    for node in root.findall("./channel/item")[:50]:
        url = (node.findtext("link") or "").strip()
        target = urlsplit(url)
        if (
            target.scheme != "https"
            or target.hostname != "www.federalreserve.gov"
            or target.username
            or target.password
            or target.port not in (None, 443)
            or len(url) > 2000
        ):
            continue
        title = plain(node.findtext("title") or "", 1000)
        identity = (node.findtext("guid") or url).strip()
        if not title or not identity or len(identity) > 1000 or identity in seen:
            continue
        published = None
        try:
            candidate = parsedate_to_datetime(node.findtext("pubDate") or "")
            if candidate.tzinfo:
                published = candidate.astimezone(UTC)
        except (ValueError, TypeError, OverflowError):
            pass
        seen.add(identity)
        entries.append(
            FeedEntry(
                identity, title, plain(node.findtext("description") or "", 4000), url, published
            )
        )
    return entries


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
        "Accept": "application/rss+xml, application/xml, text/xml",
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
