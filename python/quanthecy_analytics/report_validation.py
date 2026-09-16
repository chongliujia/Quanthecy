"""Strict local JSON parsing and redacted validation diagnostics (no model retry)."""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

IssueCode = Literal[
    "invalid_json",
    "invalid_shape",
    "missing_field",
    "extra_field",
    "invalid_type",
    "invalid_value",
    "too_long",
    "too_many",
    "unknown_reference",
    "unknown_signal",
    "output_size",
    "forecast_not_supported",
    "forecast_bounds",
]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    code: IssueCode


class ListGrouping(BaseModel):
    """Audit metadata only; no provider text is included here."""

    model_config = ConfigDict(extra="forbid")
    field: Literal["limitations", "watch_for", "risk_flags", "follow_up"]
    original_count: int
    grouped_count: int
    method: Literal["consecutive_text_grouping_v1"] = "consecutive_text_grouping_v1"


def group_narrative_lists(value: dict[str, Any], schema: dict[str, Any]) -> list[ListGrouping]:
    """Group consecutive text items without deletion, rewriting, deduplication or retries.

    Only these narrative fields are eligible. Citations, claims, enums and forecast
    fields are never repaired. Invalid/oversized strings still fail validation.
    The schema and existing whole-result memory budget remain authoritative.
    """
    changes = []
    for name in ("limitations", "watch_for", "risk_flags", "follow_up"):
        field = schema.get("properties", {}).get(name, {})
        maximum = field.get("maxItems")
        text_limit = field.get("items", {}).get("maxLength")
        items = value.get(name)
        if (
            not isinstance(maximum, int)
            or maximum < 1
            or not isinstance(text_limit, int)
            or not isinstance(items, list)
            or not maximum < len(items) <= 64
            or any(not isinstance(item, str) or not 1 <= len(item) <= text_limit for item in items)
        ):
            continue

        def render(group: list[str]) -> str:
            return group[0] if len(group) == 1 else "• " + "\n• ".join(group)

        # Greedy maximal prefixes give the fewest order-preserving groups.
        groups: list[list[str]] = []
        for item in items:
            if groups and len(render([*groups[-1], item])) <= text_limit:
                groups[-1].append(item)
            else:
                groups.append([item])
        if len(groups) > maximum:
            continue  # Cannot fit losslessly: retain the original validation failure.
        # Use the available slots to keep the result readable, preserving order.
        while len(groups) < maximum:
            index = max(range(len(groups)), key=lambda i: len(groups[i]))
            group = groups[index]
            midpoint = (len(group) + 1) // 2
            groups[index : index + 1] = [group[:midpoint], group[midpoint:]]
        value[name] = [render(group) for group in groups]
        changes.append(
            ListGrouping.model_validate(
                {
                    "field": name,
                    "original_count": len(items),
                    "grouped_count": len(groups),
                }
            )
        )
    return changes


class ReportValidationError(ValueError):
    def __init__(self, code: IssueCode, field: str = "output") -> None:
        self.issues = [ValidationIssue(field=field, code=code)]
        # Fixed categories only; never include provider text or unknown reference IDs.
        super().__init__(f"{code}: {field}")


def parse_report(raw: str) -> dict[str, Any]:
    text = raw.strip().lstrip("\ufeff").strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReportValidationError("invalid_json")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ReportValidationError("invalid_json")

    try:
        result = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise ReportValidationError("invalid_json") from None
    if not isinstance(result, dict):
        raise ReportValidationError("invalid_shape")
    return result


def validation_issues(exc: Exception) -> list[dict[str, str]]:
    if isinstance(exc, ReportValidationError):
        return [issue.model_dump() for issue in exc.issues]
    if not isinstance(exc, ValidationError):
        return [{"field": "output", "code": "invalid_value"}]
    # Provider-controlled extra keys must not become diagnostic field names.
    fields = {
        "summary",
        "findings",
        "challenges",
        "limitations",
        "watch_for",
        "kind",
        "text",
        "references",
        "action",
        "confidence",
        "thesis",
        "claims",
        "counter_evidence",
        "key_signals",
        "risk_flags",
        "follow_up",
        "disagreements",
        "forecast",
        "status",
        "target",
        "probability",
        "lower",
        "upper",
        "rationale",
        "assumptions",
        "invalidation_triggers",
        "calibration",
    }
    codes: dict[str, IssueCode] = {
        "missing": "missing_field",
        "extra_forbidden": "extra_field",
        "json_invalid": "invalid_json",
        "string_too_long": "too_long",
        "too_long": "too_many",
        "model_type": "invalid_shape",
        "string_type": "invalid_type",
        "list_type": "invalid_type",
        "dict_type": "invalid_type",
        "float_type": "invalid_type",
        "float_parsing": "invalid_type",
    }
    result = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]:
        parts = [
            str(p)
            if isinstance(p, int) and 0 <= p < 100
            else p
            if isinstance(p, str) and p in fields
            else "field"
            for p in error["loc"]
        ]
        code = codes.get(error["type"], "invalid_value")
        if error["type"] == "value_error" and "forecast" in parts:
            code = "forecast_bounds"
        result.append({"field": ".".join(parts) or "output", "code": code})
    return result
