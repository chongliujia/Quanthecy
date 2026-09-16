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
