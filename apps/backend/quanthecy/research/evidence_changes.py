"""Bounded differences between saved versions, not inferred market impact."""

from typing import Any

from .documents import OfficialDocument
from .models import EvidenceRevision


def revision_changes(
    current: EvidenceRevision, previous: EvidenceRevision | None
) -> dict[str, Any]:
    if previous is None:
        return {
            "kind": "FIRST_OBSERVED",
            "previous_revision_id": None,
            "changed_fields": [],
            "added": [],
            "removed": [],
        }
    fields = [
        key
        for key in ("title", "excerpt", "url", "published_at")
        if getattr(current, key) != getattr(previous, key)
    ]
    old = OfficialDocument.model_validate(previous.document).text if previous.document else ""
    new = OfficialDocument.model_validate(current.document).text if current.document else ""
    if old != new:
        fields.append("document")
    old_parts, new_parts = old.split("\n\n") if old else [], new.split("\n\n") if new else []
    old_set, new_set = set(old_parts), set(new_parts)
    added = [(i, p) for i, p in enumerate(new_parts, 1) if p not in old_set]
    removed = [(i, p) for i, p in enumerate(old_parts, 1) if p not in new_set]

    def bounded(parts: list[tuple[int, str]]) -> list[dict[str, Any]]:
        return [{"paragraph": i, "text": p[:350], "truncated": len(p) > 350} for i, p in parts[:2]]

    return {
        "kind": "REVISION",
        "previous_revision_id": str(previous.id),
        "previous_observed_at": previous.observed_at.isoformat(),
        "changed_fields": fields,
        "added": bounded(added),
        "removed": bounded(removed),
        "truncated": len(added) > 2 or len(removed) > 2,
        "previous_excerpt": previous.excerpt[:350] if "excerpt" in fields else None,
        "previous_excerpt_truncated": len(previous.excerpt) > 350 if "excerpt" in fields else False,
    }
