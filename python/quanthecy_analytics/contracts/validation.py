import json
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .market import MarketObservation, market_schema

_VALIDATOR = Draft202012Validator(market_schema(), format_checker=FormatChecker())


def validate_observation(payload: str | bytes) -> MarketObservation:
    """Validate the wire format before constructing the typed Python model."""

    def reject_constant(value: str) -> Any:
        raise ValueError(f"Non-finite JSON number: {value}")

    data = json.loads(payload, parse_constant=reject_constant)
    _VALIDATOR.validate(data)
    return MarketObservation.model_validate(data)
