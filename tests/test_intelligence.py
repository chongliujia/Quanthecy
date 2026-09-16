import copy
import json

import pytest
from quanthecy_analytics.intelligence import (
    SKILLS,
    Forecast,
    digest,
    scoped_context,
    stage_input,
    validate_stage,
)
from quanthecy_analytics.report_validation import validation_issues


def claim(reference="market"):
    return {"kind": "HYPOTHESIS", "text": "Bounded evidence only.", "references": [reference]}


def specialist(reference="market"):
    return {
        "summary": claim(reference),
        "findings": [],
        "challenges": [],
        "limitations": ["Source coverage is limited."],
        "watch_for": [],
    }


def forecast(status="ABSTAIN"):
    return {
        "status": status,
        "target": "YES_AT_CONTRACT_RESOLUTION",
        "probability": 0.6 if status == "ESTIMATE" else None,
        "lower": 0.4 if status == "ESTIMATE" else None,
        "upper": 0.7 if status == "ESTIMATE" else None,
        "rationale": claim("news" if status == "ESTIMATE" else "market"),
        "assumptions": ["The contract rules remain unchanged."],
        "invalidation_triggers": ["A conflicting official release appears."],
        "calibration": "UNCALIBRATED",
    }


def report(status="ABSTAIN"):
    return {
        "action": "WATCH",
        "confidence": 0.6,
        "thesis": claim(),
        "claims": [],
        "counter_evidence": [],
        "key_signals": [],
        "risk_flags": [],
        "follow_up": [],
        "disagreements": [],
        "forecast": forecast(status),
    }


@pytest.fixture
def context():
    return {
        "version": "context-v2",
        "cutoff": "2026-01-01T00:00:00Z",
        "references": [
            {"id": "market", "kind": "market", "value": {}},
            {"id": "rules", "kind": "rules", "value": {}},
            {"id": "metric", "kind": "metric", "value": {"value": 0.1}},
            {"id": "news", "kind": "evidence", "value": "Untrusted source text"},
        ],
        "limitations": [],
        "quality": {"forecast_eligible": False},
        "observations": [{"raw": "not for model input"}],
    }


def test_independent_scopes_and_validated_peer_memory(context):
    originals = copy.deepcopy(context)
    for skill in SKILLS[:3]:
        packet = stage_input(context, skill, {})
        assert not packet["peer_findings"]
        assert "observations" not in packet["context"]
    quant = scoped_context(context, SKILLS[0])
    assert "news" not in {r["id"] for r in quant["references"]}
    with pytest.raises(ValueError, match="unknown_reference"):
        validate_stage(json.dumps(specialist("news")), SKILLS[0], quant)
    peers = {s.id: specialist() for s in SKILLS[:3]}
    packet = stage_input(context, SKILLS[3], peers)
    assert set(packet["peer_findings"]) == {"quant", "events", "pricing"}
    assert context == originals
    assert digest(context) == digest(originals)


def test_schema_length_and_reference_contract_match_actual_validator(context):
    packet = stage_input(context, SKILLS[0], {})
    definition = packet["output_schema"]["$defs"]["SpecialistClaim"]["properties"]
    assert definition["text"]["maxLength"] == 600
    assert set(definition["references"]["items"]["enum"]) == {"market", "rules", "metric"}
    assert packet["allowed_reference_ids"] == ["market", "metric", "rules"]
    validate_stage(json.dumps(packet["output_example"]), SKILLS[0], packet["context"])
    bad = specialist()
    bad["summary"]["text"] = "字" * 601
    with pytest.raises(ValueError) as error:
        validate_stage(json.dumps(bad), SKILLS[0], packet["context"])
    assert validation_issues(error.value) == [{"field": "summary.text", "code": "too_long"}]


def test_equivalent_unicode_json_whitespace_and_fences_do_not_change_memory_budget(context):
    output = specialist()
    output["summary"]["text"] = "测试" * 300
    output["findings"] = [copy.deepcopy(output["summary"]) for _ in range(4)]
    escaped = json.dumps(output, ensure_ascii=True, indent=4)
    assert len(escaped.encode()) > 14000
    for raw in [escaped, json.dumps(output, ensure_ascii=False), "```json\n" + escaped + "\n```"]:
        assert validate_stage(raw, SKILLS[0], context) == output


@pytest.mark.parametrize(
    "raw",
    [
        '{"summary":',
        '{"summary": null, "summary": {}}',
        'Here is the result: {"summary": {}}',
        '{"confidence": NaN}',
    ],
)
def test_malformed_json_is_not_repaired_or_silently_accepted(context, raw):
    with pytest.raises(ValueError) as error:
        validate_stage(raw, SKILLS[0], context)
    assert validation_issues(error.value) == [{"field": "output", "code": "invalid_json"}]


def test_diagnostics_do_not_include_provider_text_extra_keys_or_unknown_ids(context):
    output = specialist()
    output["provider-secret-in-extra-key"] = "private-provider-response"
    output["summary"]["kind"] = "private-provider-value"
    with pytest.raises(ValueError) as error:
        validate_stage(json.dumps(output), SKILLS[0], context)
    issues = validation_issues(error.value)
    assert {i["code"] for i in issues} == {"extra_field", "invalid_value"}
    assert "provider" not in json.dumps(issues)
    with pytest.raises(ValueError) as error:
        validate_stage(json.dumps(specialist("unknown-private-id")), SKILLS[0], context)
    assert validation_issues(error.value) == [
        {"field": "summary.references", "code": "unknown_reference"}
    ]


def test_context_budget_omissions_are_explicit_and_core_rules_never_silently_truncated(context):
    context["references"].append({"id": "long-news", "kind": "evidence", "value": "x" * 40000})
    scoped = scoped_context(context, SKILLS[1])
    assert scoped["omitted_reference_ids"] == ["long-news"]
    assert scoped["reference_bytes"] <= 32000
    context["references"][1]["value"] = "x" * 40000
    with pytest.raises(ValueError, match="Required context"):
        scoped_context(context, SKILLS[1])


@pytest.mark.parametrize(
    "changes",
    [
        {"lower": 0.8},
        {"probability": 1.01},
        {"upper": float("nan")},
        {"assumptions": []},
        {"invalidation_triggers": []},
        {"calibration": "CALIBRATED"},
    ],
)
def test_forecasts_require_valid_ranges_and_explicit_conditions(changes):
    with pytest.raises(ValueError):
        Forecast.model_validate({**forecast("ESTIMATE"), **changes})


def test_abstention_is_not_zero_probability_and_forecast_requires_event_evidence(context):
    assert (
        validate_stage(json.dumps(report()), SKILLS[-1], context)["forecast"]["probability"] is None
    )
    with pytest.raises(ValueError):
        Forecast.model_validate({**forecast(), "probability": 0})
    with pytest.raises(ValueError, match="forecast_not_supported"):
        validate_stage(json.dumps(report("ESTIMATE")), SKILLS[-1], context)
    context["quality"]["forecast_eligible"] = True
    result = validate_stage(json.dumps(report("ESTIMATE")), SKILLS[-1], context)
    assert result["forecast"]["probability"] == 0.6
    bad = report("ESTIMATE")
    bad["forecast"]["rationale"]["references"] = ["market"]
    with pytest.raises(ValueError, match="forecast_not_supported"):
        validate_stage(json.dumps(bad), SKILLS[-1], context)
    bad = report()
    bad["disagreements"] = [claim("invented")]
    with pytest.raises(ValueError, match="unknown_reference"):
        validate_stage(json.dumps(bad), SKILLS[-1], context)
