import copy
import json

import pytest
from quanthecy_analytics.intelligence import (
    SKILLS,
    Forecast,
    digest,
    instructions,
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


@pytest.mark.parametrize("skill", SKILLS[:4], ids=lambda skill: skill.id)
def test_role_list_limits_agree_in_prompt_schema_and_validator(context, skill):
    peers = {key: specialist() for key in skill.dependencies}
    packet = stage_input(context, skill, peers)
    maximum = 12
    assert packet["output_limits"]["limitations"] == maximum
    assert packet["output_schema"]["properties"]["limitations"]["maxItems"] == maximum
    assert json.dumps(packet["output_limits"], sort_keys=True) in instructions(skill, "zh")
    output = specialist()
    output["limitations"] = [f"Distinct evidence gap {i}." for i in range(maximum)]
    assert validate_stage(json.dumps(output), skill, context) == output
    output["limitations"].append("One additional gap.")
    adjustments = []
    result = validate_stage(json.dumps(output), skill, context, adjustments=adjustments)
    assert len(result["limitations"]) == maximum
    assert all(item in "\n".join(result["limitations"]) for item in output["limitations"])
    assert adjustments[0].model_dump() == {
        "field": "limitations",
        "original_count": 13,
        "grouped_count": 12,
        "method": "consecutive_text_grouping_v1",
    }


def test_expanded_risk_limit_keeps_citation_and_total_memory_checks(context):
    output = specialist("unknown-source")
    output["limitations"] = [f"Distinct gap {i}." for i in range(12)]
    with pytest.raises(ValueError, match="unknown_reference"):
        validate_stage(json.dumps(output), SKILLS[3], context)
    output["summary"] = claim()
    output["limitations"] = ["字" * 600 for _ in range(12)]
    with pytest.raises(ValueError, match="output_size"):
        validate_stage(json.dumps(output), SKILLS[3], context)


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


def test_v5_estimate_must_cite_a_directly_reviewed_version(context):
    context["version"] = "context-v5"
    context["quality"] = {"forecast_eligible": True, "reviewed_evidence_ids": ["another-version"]}
    with pytest.raises(ValueError):
        validate_stage(json.dumps(report("ESTIMATE")), SKILLS[-1], context)
    context["quality"]["reviewed_evidence_ids"] = ["news"]
    assert (
        validate_stage(json.dumps(report("ESTIMATE")), SKILLS[-1], context)["forecast"]["status"]
        == "ESTIMATE"
    )
    context["quality"]["forecast_eligible"] = False
    with pytest.raises(ValueError):
        validate_stage(json.dumps(report("ESTIMATE")), SKILLS[-1], context)


@pytest.mark.parametrize("count", [13, 36, 64])
def test_text_grouping_retains_order_unicode_qualifications_and_reports_it(context, count):
    output = specialist()
    original = [f" [第{i:03d}项] 必须保留的限制。\n• 原始说明与限定条件。 " for i in range(count)]
    output["limitations"] = original
    adjustments = []
    result = validate_stage(json.dumps(output), SKILLS[1], context, adjustments=adjustments)
    combined = "\n".join(result["limitations"])
    positions = [combined.index(item) for item in original]
    assert positions == sorted(positions) and len(set(positions)) == count
    assert all(combined.count(item) == 1 for item in original)
    assert len(result["limitations"]) == 12
    assert all(len(item) <= 600 for item in result["limitations"])
    assert adjustments[0].original_count == count


@pytest.mark.parametrize("items", [[str(i) for i in range(65)], ["x" * 600 for _ in range(13)]])
def test_unrepairable_count_overflow_is_rejected_without_losing_caveats(context, items):
    output = specialist()
    output["limitations"] = items
    adjustments = []
    with pytest.raises(ValueError) as error:
        validate_stage(json.dumps(output), SKILLS[1], context, adjustments=adjustments)
    assert validation_issues(error.value) == [{"field": "limitations", "code": "too_many"}]
    assert not adjustments


@pytest.mark.parametrize("problem", ["unknown_reference", "invalid_shape", "claim_overflow"])
def test_grouping_never_bypasses_other_validation(context, problem):
    output = specialist()
    output["limitations"] = [f"Gap {i}." for i in range(13)]
    if problem == "unknown_reference":
        output["summary"]["references"] = ["invented-source"]
    elif problem == "invalid_shape":
        output["limitations"][3] = {"text": "Not a string"}
    else:
        output["findings"] = [claim() for _ in range(5)]
    adjustments = []
    with pytest.raises(ValueError):
        validate_stage(json.dumps(output), SKILLS[1], context, adjustments=adjustments)
    assert adjustments == []


def test_synthesis_groups_risks_and_followups_but_preserves_forecast_gates(context):
    output = report()
    output["risk_flags"] = [f"Risk [{i:03d}] must survive." for i in range(18)]
    output["follow_up"] = [f"Observation [{i:03d}] must survive." for i in range(10)]
    adjustments = []
    result = validate_stage(json.dumps(output), SKILLS[-1], context, adjustments=adjustments)
    assert len(result["risk_flags"]) == 12 and len(result["follow_up"]) == 8
    for field in ("risk_flags", "follow_up"):
        assert all(item in "\n".join(result[field]) for item in output[field])
    assert [item.field for item in adjustments] == ["risk_flags", "follow_up"]
    output["forecast"] = forecast("ESTIMATE")
    with pytest.raises(ValueError, match="forecast_not_supported"):
        validate_stage(json.dumps(output), SKILLS[-1], context)
