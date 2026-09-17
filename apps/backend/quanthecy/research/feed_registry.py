"""Reviewed RSS endpoints. Database controls may pause them, never redirect them."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FeedSpec:
    name: str
    url: str
    article_hosts: tuple[str, ...]
    kind: Literal["OFFICIAL", "MEDIA"] = "OFFICIAL"
    enabled: bool = True
    notes: str = ""


FEEDS = {
    "fed-monetary": FeedSpec(
        "Federal Reserve · Monetary policy",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
        ("www.federalreserve.gov",),
    ),
    "fed-speeches": FeedSpec(
        "Federal Reserve · Speeches",
        "https://www.federalreserve.gov/feeds/speeches.xml",
        ("www.federalreserve.gov",),
    ),
    "fed-testimony": FeedSpec(
        "Federal Reserve · Testimony",
        "https://www.federalreserve.gov/feeds/testimony.xml",
        ("www.federalreserve.gov",),
    ),
    "bls-employment": FeedSpec(
        "BLS · Employment Situation",
        "https://www.bls.gov/feed/empsit.rss",
        ("www.bls.gov", "bls.gov"),
        enabled=False,
        notes="Initial deployment probe returned HTTP 403. Enable after checking network access.",
    ),
    "bea-releases": FeedSpec(
        "BEA · Economic releases",
        "https://apps.bea.gov/rss/rss.xml",
        ("www.bea.gov", "apps.bea.gov", "bea.gov"),
    ),
    "bls-cpi": FeedSpec(
        "BLS · Consumer Price Index",
        "https://www.bls.gov/feed/cpi.rss",
        ("www.bls.gov", "bls.gov"),
        enabled=False,
        notes="Initial deployment probe returned HTTP 403. Enable after checking network access.",
    ),
    "bbc-business": FeedSpec(
        "BBC · Business",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        ("www.bbc.co.uk", "www.bbc.com", "bbc.co.uk", "bbc.com"),
        kind="MEDIA",
    ),
    "cnbc-economy": FeedSpec(
        "CNBC · Economy",
        "https://www.cnbc.com/id/20910258/device/rss/rss.html",
        ("www.cnbc.com", "cnbc.com"),
        kind="MEDIA",
    ),
}

OFFICIAL_SOURCES = frozenset(slug for slug, spec in FEEDS.items() if spec.kind == "OFFICIAL")
