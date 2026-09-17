"""Deterministic candidate discovery, never an event forecast or an approval."""

import re
from datetime import timedelta
from typing import Any

from .documents import OfficialDocument
from .models import EventDefinition, EvidenceRevision

FED = re.compile(r"\b(?:federal reserve|FOMC|Fed)\b", re.IGNORECASE)
POLICY = re.compile(
    r"\b(?:interest rates?|policy rates?|monetary policy|inflation|employment|"
    r"unemployment|rate cuts?|rate hikes?|federal funds)\b",
    re.IGNORECASE,
)
MACRO = re.compile(
    r"\b(?:GDP|gross domestic product|consumer price index|CPI|PCE|"
    r"personal (?:income|consumption)|employment situation|nonfarm payrolls?|"
    r"inflation|unemployment)\b",
    re.IGNORECASE,
)
US = re.compile(r"\b(?:U\.?S\.?|United States|American)\b", re.IGNORECASE)


def discover(definition: EventDefinition, revision: EvidenceRevision) -> dict[str, Any] | None:
    if revision.item.source_id not in definition.source_slugs:
        return None
    if definition.discovery_policy == "source-only-v1":
        return {
            "method": "source-only-v1",
            "priority": 0,
            "reasons": ["SELECTED_SOURCE"],
            "matches": [],
        }
    if definition.discovery_policy != "fed-macro-v1":
        return None
    lower = definition.starts_on - timedelta(days=180)
    upper = definition.ends_on + timedelta(days=7)
    if revision.published_at and not lower <= revision.published_at.date() <= upper:
        return None
    parts: list[tuple[str, int | None, str]] = [
        ("title", None, revision.title),
        ("excerpt", None, revision.excerpt),
    ]
    if revision.document:
        document = OfficialDocument.model_validate(revision.document)
        parts += [("paragraph", i, p) for i, p in enumerate(document.text.split("\n\n"), 1)]
    # Match within each original field/paragraph; do not fabricate cross-paragraph claims.
    selected: list[dict[str, Any]] = []
    reasons: set[str] = set()
    fed_source = revision.item.source_id.startswith("fed-")
    macro_source = (
        revision.item.source_id.startswith("bls-") or revision.item.source_id == "bea-releases"
    )
    month = definition.starts_on.strftime("%B")
    specific = re.compile(
        rf"\b{month}\s+(?:\d{{1,2}}(?:[–-]\d{{1,2}})?[,]?\s+)?{definition.starts_on.year}\b",
        re.IGNORECASE,
    )
    for field, number, text in parts:
        fed_policy = bool(POLICY.search(text) and (fed_source or FED.search(text)))
        macro = bool(MACRO.search(text) and (fed_source or macro_source or US.search(text)))
        if not fed_policy and not macro:
            continue
        reasons.add("FED_POLICY_TERMS" if fed_policy else "US_MACRO_TERMS")
        if fed_policy and specific.search(text):
            reasons.add("EVENT_MONTH_MENTION")
        if len(selected) < 3:
            pattern = POLICY if fed_policy else MACRO
            match = pattern.search(text)
            start = max(0, match.start() - 100) if match else 0
            selected.append(
                {
                    "field": field,
                    "paragraph": number,
                    "text": text[start : start + 500],
                    "truncated": start > 0 or len(text) > 500,
                }
            )
    if not reasons:
        return None
    priority = (
        30 if "EVENT_MONTH_MENTION" in reasons else 20 if "FED_POLICY_TERMS" in reasons else 10
    )
    reasons.add("PUBLICATION_IN_WINDOW" if revision.published_at else "PUBLICATION_UNKNOWN")
    return {
        "method": "fed-macro-v1",
        "priority": priority,
        "reasons": sorted(reasons),
        "matches": selected,
        "window_start": lower.isoformat(),
        "window_end": upper.isoformat(),
    }
