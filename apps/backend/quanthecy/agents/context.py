import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from quanthecy_analytics.intelligence import digest
from quanthecy_analytics.quality import research_quality
from quanthecy_analytics.signals import analyze

from quanthecy.markets.repositories import history_repository
from quanthecy.research.documents import OfficialDocument, evidence_passages
from quanthecy.research.events import event_list, market_event_evidence
from quanthecy.research.models import EvidenceRevision
from quanthecy.research.schemas import EvidenceOut, LinkOut, TimelineEntry
from quanthecy.research.services import comparisons, timeline


def build_context(market_id: UUID, cutoff: datetime) -> dict[str, Any]:
    rows = history_repository().history(
        market_id,
        start=(cutoff - timedelta(minutes=20)).isoformat(),
        end=cutoff.isoformat(),
        known_at=cutoff.isoformat(),
        limit=1001,
    )
    rows = sorted(
        [
            row
            for row in rows
            if datetime.fromisoformat(row["recorded_at"]) <= cutoff
            and datetime.fromisoformat(row["received_at"]) <= cutoff
        ],
        key=lambda row: (row["received_at"], row["observation_id"]),
    )
    if not rows or len(rows) > 1000:
        raise ValidationError("No complete bounded history available.")
    metrics, signals = analyze(rows)
    latest = rows[-1]
    entries = timeline(market_id, cutoff)
    reviews = [
        review
        for review in comparisons(cutoff)
        if market_id in (review.left_snapshot.market.id, review.right_snapshot.market.id)
    ]
    references: list[dict[str, Any]] = [
        {
            "id": "market",
            "kind": "market",
            "label": latest["market"]["title"],
            "value": {
                "platform": latest["platform"],
                "outcome": latest["outcome"],
                "observed_at": latest["received_at"],
                "probability": latest["probability"],
                "best_bid": latest["best_bid"],
                "best_ask": latest["best_ask"],
                "liquidity": latest["liquidity"],
                "quality_flags": latest["quality_flags"],
            },
        },
        {
            "id": "rules",
            "kind": "rules",
            "label": "Contract resolution rules",
            "value": latest["market"],
        },
    ]
    for name in ("probability_change_15m", "spread_change_15m", "volume_zscore"):
        references.append(
            {
                "id": f"metric:{name}",
                "kind": "metric",
                "label": name.replace("_", " "),
                "value": {
                    "value": metrics[name],
                    "unit": "probability_fraction" if "change" in name else "z_score",
                    "calculation": metrics,
                },
            }
        )
    for signal in signals:
        references.append(
            {"id": signal["id"], "kind": "signal", "label": signal["signal_type"], "value": signal}
        )
    event_evidence = market_event_evidence(market_id, cutoff)
    reviewed: dict[str, list[dict[str, Any]]] = {}
    rejected = set()
    for item in event_evidence:
        candidate = item["candidate"]
        revision_id = candidate["evidence"]["revision_id"]
        if candidate["status"] == "UNRELATED":
            rejected.add(revision_id)
        elif candidate["status"] in ("DIRECT", "BACKGROUND"):
            reviewed.setdefault(revision_id, []).append(item)
    selected_entries = [
        entry
        for entry in entries.items
        if str(entry.evidence.revision_id) not in rejected
        or str(entry.evidence.revision_id) in reviewed
    ]
    present = {str(entry.evidence.revision_id) for entry in selected_entries}
    for revision_id, items in reviewed.items():
        if revision_id not in present:
            candidate = items[0]["candidate"]
            selected_entries.append(
                TimelineEntry(
                    evidence=EvidenceOut(**candidate["evidence"]),
                    association=LinkOut(
                        id=candidate["id"],
                        market_id=market_id,
                        status="REVIEWED",
                        rationale=candidate["review"]["rationale"],
                        method="event-review-v1",
                        created_at=candidate["review"]["reviewed_at"],
                    ),
                )
            )
    selected_entries.sort(
        key=lambda entry: (
            0
            if any(
                v["candidate"]["status"] == "DIRECT"
                for v in reviewed.get(str(entry.evidence.revision_id), [])
            )
            else 1
            if str(entry.evidence.revision_id) in reviewed
            else 2
        )
    )
    selected_entries = selected_entries[:8]
    references[0]["value"]["research_events"] = [
        {
            "slug": event.slug,
            "title": event.title,
            "definition_id": str(event.definition_id),
            "starts_on": event.starts_on.isoformat(),
            "ends_on": event.ends_on.isoformat(),
            "scope": event.scope[:600],
            "scope_truncated": len(event.scope) > 600,
            "calendar_url": event.calendar_url,
            "observed_at": event.observed_at.isoformat(),
        }
        for event in event_list(cutoff, market_id)[:3]
    ]
    direct_ids = []
    evidence_versions = EvidenceRevision.objects.defer("raw_document").in_bulk(
        [entry.evidence.revision_id for entry in selected_entries]
    )
    for entry in selected_entries:
        value = entry.model_dump(mode="json")
        excerpt = entry.evidence.excerpt.encode()[:800].decode("utf-8", errors="ignore")
        value["evidence"]["excerpt"] = excerpt
        value["evidence"]["excerpt_truncated"] = excerpt != entry.evidence.excerpt
        revision = evidence_versions.get(entry.evidence.revision_id)
        if revision and revision.document:
            document = OfficialDocument.model_validate(revision.document)
            if revision.observed_at <= cutoff and document.observed_at <= cutoff:
                value["document_selection"] = evidence_passages(document)
        event_reviews = reviewed.get(str(entry.evidence.revision_id), [])[:2]
        if event_reviews:
            value["event_reviews"] = [
                {
                    "event_slug": v["event"]["slug"],
                    "definition_id": v["event"]["definition_id"],
                    "review": {
                        **v["candidate"]["review"],
                        "rationale": v["candidate"]["review"]["rationale"][:600],
                        "rationale_truncated": len(v["candidate"]["review"]["rationale"]) > 600,
                    },
                }
                for v in event_reviews
            ]
            if revision and revision.document:
                paragraphs = OfficialDocument.model_validate(revision.document).text.split("\n\n")
                numbers = list(
                    dict.fromkeys(
                        n for v in event_reviews for n in v["candidate"]["review"]["paragraphs"]
                    )
                )[:3]
                if numbers:
                    passages = []
                    for n in numbers:
                        text = paragraphs[n - 1].encode()[:600].decode("utf-8", errors="ignore")
                        passages.append(
                            {"paragraph": n, "text": text, "truncated": text != paragraphs[n - 1]}
                        )
                    value["document_selection"] = {
                        "method": "operator-reviewed-paragraphs-v1",
                        "passages": passages,
                        "selection_truncated": True,
                    }
            if any(v["candidate"]["status"] == "DIRECT" for v in event_reviews):
                direct_ids.append(str(entry.evidence.revision_id))
        references.append(
            {
                "id": str(entry.evidence.revision_id),
                "kind": "evidence",
                "label": entry.evidence.title,
                "url": entry.evidence.url,
                "value": value,
            }
        )
    for review in reviews[:5]:
        references.append(
            {
                "id": str(review.id),
                "kind": "comparison",
                "label": review.title,
                "value": review.model_dump(mode="json"),
            }
        )
    limitations = [
        "REST snapshots; exchange quote time is unavailable. "
        "Topic and timing do not establish causation. Media feed excerpts are secondary "
        "reports, not official statements or independent confirmation of one another.",
        "Official document passages are bounded excerpts selected by policy terms, not the "
        "complete article. Omitted passages may qualify or contradict an interpretation. "
        "Captured text covers the source page only; linked articles and PDF attachments "
        "are not included. A minutes release is not the full meeting minutes. "
        "A speech expresses the speaker's views, not a committee decision.",
    ]
    if not metrics["history_ready"]:
        limitations.append(f"Analytics unavailable: {metrics['reason']}.")
    if (cutoff - datetime.fromisoformat(latest["received_at"])).total_seconds() > 180:
        limitations.append("The latest available quote is stale at the research cutoff.")
    if not direct_ids:
        limitations.append(
            "No version-bound, directly relevant event evidence has been reviewed. "
            "Event probability estimates must be withheld; "
            "background and topic matches are insufficient."
        )
    if not entries.items:
        limitations.append("No associated news evidence was available at this cutoff.")
    if not reviews:
        limitations.append("No reviewed cross-platform comparison available.")
    if len(entries.items) > 8 or entries.truncated or len(reviews) > 5:
        limitations.append(
            "Evidence context is bounded to eight news revisions and five comparisons."
        )
    stale = (cutoff - datetime.fromisoformat(latest["received_at"])).total_seconds() > 180
    data_quality = research_quality(latest, metrics, cutoff)
    if data_quality.reasons:
        limitations.append("Research data restrictions: " + ", ".join(data_quality.reasons) + ".")
    quality = {
        "history_ready": metrics["history_ready"],
        "stale": stale,
        "data": data_quality.model_dump(mode="json"),
        "reviewed_evidence_ids": direct_ids,
        "forecast_eligible": bool(
            data_quality.price_usable
            and direct_ids
            and latest["probability"]
            and latest["probability"]["basis"] == "MIDPOINT"
            and latest["market"]["status"] == "OPEN"
            and latest["market"]["resolution_rules"].strip()
            and latest["market"]["closes_at"]
            and datetime.fromisoformat(latest["market"]["closes_at"]) > cutoff
        ),
    }
    context = {
        "version": "context-v5",
        "cutoff": cutoff.isoformat(),
        "references": references,
        "limitations": limitations,
        "quality": quality,
    }
    if len(json.dumps(context)) > 48000:
        raise ValidationError("context_too_large")
    # Full immutable inputs stay in our database; the model receives references and metrics only.
    return {
        **context,
        "observations": rows,
        "manifest": {
            "sha256": digest(context),
            "reference_count": len(references),
            "observation_count": len(rows),
            "window_minutes": 20,
            "observation_sha256": digest(rows),
        },
    }
