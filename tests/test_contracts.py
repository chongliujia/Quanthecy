import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError
from quanthecy_analytics.contracts.market import market_schema
from quanthecy_analytics.contracts.validation import validate_observation

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
INVALID = json.loads((FIXTURES / "invalid-observations.json").read_text())


@pytest.mark.parametrize("platform", ["polymarket", "kalshi"])
def test_normalized_fixture(platform):
    observation = validate_observation((FIXTURES / platform / "observation.json").read_bytes())
    assert observation.platform == platform
    assert observation.outcome.label == "Yes"
    assert observation.probability.value == 0.6


@pytest.mark.parametrize("case", INVALID, ids=[case["name"] for case in INVALID])
def test_shared_invalid_cases(case):
    value = json.loads((FIXTURES / "polymarket/observation.json").read_text())
    path = case["path"].strip("/").split("/")
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = case["value"]
    with pytest.raises(ValidationError):
        validate_observation(json.dumps(value))


def test_nullable_data_does_not_become_zero():
    value = json.loads((FIXTURES / "kalshi/observation.json").read_text())
    value.update(
        probability=None,
        best_bid=None,
        best_ask=None,
        volume=None,
        event_at=None,
        quality_flags=["PARTIAL", "SOURCE_TIME_MISSING"],
    )
    observation = validate_observation(json.dumps(value))
    assert observation.probability is None and observation.volume is None


def test_rejects_extra_fields_and_nonfinite_numbers():
    value = json.loads((FIXTURES / "polymarket/observation.json").read_text())
    extra = deepcopy(value)
    extra["probability"]["unexpected"] = True
    with pytest.raises(ValidationError):
        validate_observation(json.dumps(extra))
    for invalid in [float("nan"), float("inf")]:
        value["probability"]["value"] = invalid
        with pytest.raises(ValueError):
            validate_observation(json.dumps(value))


def test_checked_in_schema_matches_authoring_model():
    assert (
        json.loads((ROOT / "contracts/v1/market-observation.schema.json").read_text())
        == market_schema()
    )
