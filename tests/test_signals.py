import copy
import io
import json
from pathlib import Path

import polars as pl
import pytest
from quanthecy_analytics.contracts.validation import validate_observation
from quanthecy_analytics.exports import export_observations
from quanthecy_analytics.signals import analyze

FIXTURE = Path(__file__).parent / "fixtures/research-window.json"


def test_signals_reproduce_all_three_families_from_saved_observations():
    rows = json.loads(FIXTURE.read_text())
    for row in rows:
        validate_observation(json.dumps(row))
    metrics, signals = analyze(rows)
    assert metrics["history_ready"]
    assert metrics["probability_change_15m"] == pytest.approx(0.09)
    assert metrics["spread_change_15m"] == pytest.approx(0.06)
    assert {s["signal_type"] for s in signals} == {
        "PROBABILITY_SPIKE",
        "SPREAD_WIDENING",
        "VOLUME_SPIKE",
    }
    assert len({s["id"] for s in signals}) == 3
    assert analyze(list(reversed(rows)) + [rows[0]]) == (metrics, signals)


@pytest.mark.parametrize("file_format", ["csv", "parquet"])
def test_export_roundtrip_preserves_exact_signal_inputs(file_format):
    rows = json.loads(FIXTURE.read_text())
    data = export_observations(rows, file_format)
    frame = (pl.read_csv if file_format == "csv" else pl.read_parquet)(io.BytesIO(data))
    restored = [json.loads(value) for value in frame["envelope_json"]]
    assert restored == rows
    assert analyze(restored) == analyze(rows)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("gap", "sampling_gap_or_invalid_quote"),
        ("rules", "incompatible_observations"),
        ("outcome", "incompatible_observations"),
        ("closed", "market_not_open"),
        ("rules_missing", "missing_resolution_rules"),
    ],
)
def test_incompatible_windows_do_not_emit_signals(mutation, reason):
    rows = json.loads(FIXTURE.read_text())
    if mutation == "gap":
        rows[5]["quality_flags"].append("GAP")
    elif mutation == "rules":
        rows[5]["market"]["rules_version"] = "revised"
    elif mutation == "outcome":
        rows[5]["outcome"]["id"] = rows[5]["market"]["id"]
    elif mutation == "rules_missing":
        rows[5]["market"]["resolution_rules"] = ""
    else:
        rows[-1]["market"]["status"] = "CLOSED"
    metrics, signals = analyze(rows)
    assert not signals
    assert metrics["reason"] == reason


def test_short_history_counter_reset_and_missing_quotes_are_not_fabricated():
    rows = json.loads(FIXTURE.read_text())
    assert analyze(rows[1:])[0]["reason"] == "insufficient_history"
    rows[-1]["volume"]["value"] = 0
    rows[-1]["probability"] = None
    metrics, signals = analyze(rows)
    assert metrics["volume_zscore"] is None
    assert metrics["probability_change_15m"] is None
    assert not signals
    missing = copy.deepcopy(rows[-1])
    missing["volume"] = None
    for file_format in ("csv", "parquet"):
        data = export_observations([missing], file_format)
        frame = (pl.read_csv if file_format == "csv" else pl.read_parquet)(io.BytesIO(data))
        assert frame["probability"][0] is None
        assert frame["volume"][0] is None
