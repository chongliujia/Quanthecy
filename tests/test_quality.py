import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from quanthecy_analytics.quality import research_quality
from quanthecy_analytics.signals import analyze, replay


@pytest.fixture
def rows():
    return json.loads((Path(__file__).parent / "fixtures/research-window.json").read_text())


@pytest.mark.parametrize(
    "problem", ["mismatch", "crossed", "missing", "nonfinite", "basis", "time"]
)
def test_bad_price_blocks_price_signals_but_valid_volume_remains_available(rows, problem):
    row = rows[6]
    if problem == "mismatch":
        row["probability"]["value"] = 0.99
    elif problem == "crossed":
        row["best_bid"] = 0.9
    elif problem == "missing":
        row["probability"] = None
    elif problem == "nonfinite":
        row["probability"]["value"] = float("nan")
    elif problem == "basis":
        row["probability"]["basis"] = "LAST_TRADE"
    else:
        row["probability"]["as_of"] = rows[-1]["received_at"]
    metrics, signals = analyze(rows)
    assert metrics["probability_change_15m"] is None
    assert metrics["spread_change_15m"] is None
    assert metrics["quality"]["price_reasons"]
    assert {s["signal_type"] for s in signals} == {"VOLUME_SPIKE"}
    quality = research_quality(rows[-1], metrics, datetime.fromisoformat(rows[-1]["received_at"]))
    assert quality.state == "limited" and not quality.price_usable and quality.volume_usable


@pytest.mark.parametrize(
    "problem,reason",
    [
        ("reset", "volume_counter_reset"),
        ("unit", "volume_basis_changed"),
        ("constant", "constant_volume_baseline"),
        ("missing", "missing_volume"),
        ("time", "invalid_volume_time"),
        ("rolling", "invalid_volume"),
    ],
)
def test_bad_volume_does_not_hide_usable_price_history(rows, problem, reason):
    if problem == "reset":
        rows[-1]["volume"]["value"] = 0
    elif problem == "unit":
        rows[6]["volume"]["unit"] = "CONTRACTS"
    elif problem == "constant":
        for row in rows:
            row["volume"]["value"] = 100
    elif problem == "missing":
        rows[6]["volume"] = None
    elif problem == "time":
        rows[-1]["volume"]["as_of"] = rows[0]["received_at"]
    else:
        rows[6]["volume"]["window_start"] = rows[0]["received_at"]
    metrics, signals = analyze(rows)
    assert metrics["volume_zscore"] is None
    assert reason in metrics["quality"]["volume_reasons"]
    assert {s["signal_type"] for s in signals} == {"PROBABILITY_SPIKE", "SPREAD_WIDENING"}
    assert metrics["quality"]["price_usable"] and not metrics["quality"]["volume_usable"]


def test_conflicting_duplicate_is_blocked_but_identical_retry_is_idempotent(rows):
    assert analyze([*rows, rows[4]]) == analyze(rows)
    conflict = copy.deepcopy(rows[4])
    conflict["volume"]["value"] += 1
    for inputs in ([*rows, conflict], [conflict, *rows]):
        metrics, signals = analyze(inputs)
        assert metrics["reason"] == "conflicting_duplicate"
        assert not signals


@pytest.mark.parametrize("flag", ["PARTIAL", "STALE", "GAP", "CROSSED_BOOK", "OUT_OF_ORDER"])
def test_excluded_flags_never_generate_research_signals(rows, flag):
    rows[5]["quality_flags"].append(flag)
    metrics, signals = analyze(rows)
    assert not signals
    assert not metrics["quality"]["price_usable"] and not metrics["quality"]["volume_usable"]


def test_freshness_future_time_pending_analytics_and_bounded_history(rows):
    metrics, _ = analyze(rows)
    now = datetime.fromisoformat(rows[-1]["received_at"])
    quality = research_quality(rows[-1], metrics, now)
    assert quality.state == "ready"
    assert quality.limitations == ["liquidity_unavailable", "source_time_missing"]
    assert research_quality(rows[-1], metrics, now + timedelta(seconds=180)).state == "ready"
    assert (
        "stale_observation"
        in research_quality(rows[-1], metrics, now + timedelta(seconds=181)).reasons
    )
    assert (
        "future_observation"
        in research_quality(rows[-1], metrics, now - timedelta(microseconds=1)).reasons
    )
    assert "quality_not_evaluated" in research_quality(rows[-1], {}, now).reasons
    newer = copy.deepcopy(rows[-1])
    newer["observation_id"] = rows[0]["observation_id"]
    assert "analytics_pending" in research_quality(newer, metrics, now).reasons
    truncated, signals = analyze(rows, truncated=True)
    assert not signals and truncated["reason"] == "history_truncated"
    rows[5]["recorded_at"] = rows[0]["received_at"]
    invalid, signals = analyze(rows)
    assert not signals and "invalid_recording_time" in invalid["quality"]["common_reasons"]


def test_existing_signal_versions_remain_reproducible(rows):
    legacy_metrics, legacy_signals = replay("rest-window-v1", rows)
    metrics, signals = replay("rest-window-v2", rows)
    assert legacy_metrics["version"] == "rest-window-v1"
    assert "quality" not in legacy_metrics
    assert metrics["probability_change_15m"] == legacy_metrics["probability_change_15m"]
    assert {s["id"] for s in signals}.isdisjoint({s["id"] for s in legacy_signals})
    with pytest.raises(ValueError, match="Unsupported"):
        replay("unknown", rows)


@pytest.mark.parametrize("missing", ["bid", "volume"])
def test_adapter_partial_flags_only_block_the_affected_indicator(rows, missing):
    rows[5]["quality_flags"].append("PARTIAL")
    if missing == "bid":
        rows[5]["best_bid"] = None
        rows[5]["probability"] = None
    else:
        rows[5]["volume"] = None
    metrics, signals = analyze(rows)
    assert metrics["quality"]["price_usable"] is (missing != "bid")
    assert metrics["quality"]["volume_usable"] is (missing != "volume")
    assert signals
