import copy
import json
import math
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


@pytest.mark.parametrize("direction", [-1, 1])
def test_serialization_noise_does_not_invalidate_volume_or_mutate_inputs(rows, direction):
    # The September audit found a four-ULP decrease at this counter size.
    base = 48732713.555604056
    for row in rows:
        row["volume"]["value"] += base
    previous = rows[5]["volume"]["value"]
    rows[6]["volume"]["value"] = previous + direction * 4 * math.ulp(previous)
    original = copy.deepcopy(rows)
    metrics, signals = analyze(rows)
    assert metrics["quality"]["volume_usable"]
    assert metrics["volume_zscore"] is not None
    assert "VOLUME_SPIKE" in {s["signal_type"] for s in signals}
    assert rows == original
    assert analyze(list(reversed(rows)) + [rows[6]]) == (metrics, signals)
    if direction == -1:
        legacy, _ = replay("rest-window-v2", rows)
        assert legacy["quality"]["volume_reasons"] == ["volume_counter_reset"]


def test_precision_only_activity_keeps_constant_baseline_unavailable(rows):
    base = 48732713.555604056
    for index, row in enumerate(rows):
        row["volume"]["value"] = base + (index % 3 - 1) * 4 * math.ulp(base)
    metrics, signals = analyze(rows)
    assert metrics["quality"]["volume_reasons"] == ["constant_volume_baseline"]
    assert metrics["volume_rate"] == 0
    assert metrics["volume_zscore"] is None
    assert "VOLUME_SPIKE" not in {s["signal_type"] for s in signals}


def test_small_negative_final_increment_uses_zero_rate_instead_of_reset(rows):
    previous = rows[-2]["volume"]["value"]
    rows[-1]["volume"]["value"] = previous - 5e-10
    metrics, signals = analyze(rows)
    assert metrics["quality"]["volume_usable"]
    assert metrics["volume_rate"] == 0
    assert metrics["volume_zscore"] < 0
    assert "VOLUME_SPIKE" not in {s["signal_type"] for s in signals}


@pytest.mark.parametrize("base,drop", [(1.0, 1e-8), (48732713.0, 0.01), (1e12, 0.01)])
def test_real_decrease_remains_a_reset_even_for_large_counters(rows, base, drop):
    for row in rows:
        row["volume"]["value"] += base
    rows[-1]["volume"]["value"] = rows[-2]["volume"]["value"] - drop
    metrics, signals = analyze(rows)
    assert metrics["quality"]["volume_reasons"] == ["volume_counter_reset"]
    assert metrics["quality"]["price_usable"]
    assert "VOLUME_SPIKE" not in {s["signal_type"] for s in signals}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_counters_cannot_be_hidden_by_tolerance(rows, value):
    rows[6]["volume"]["value"] = value
    metrics, _ = analyze(rows)
    assert not metrics["quality"]["volume_usable"]
    assert "invalid_volume" in metrics["quality"]["volume_reasons"]


def test_old_quality_requires_recalculation_and_new_signal_ids_are_distinct(rows):
    old_metrics, old_signals = replay("rest-window-v2", rows)
    metrics, signals = analyze(rows)
    assert old_metrics["quality"]["version"] == "research-quality-v1"
    assert metrics["quality"]["version"] == "research-quality-v2"
    assert metrics["version"] == "rest-window-v3"
    assert {s["id"] for s in signals}.isdisjoint(s["id"] for s in old_signals)
    assert replay("rest-window-v3", rows) == (metrics, signals)
    at = datetime.fromisoformat(rows[-1]["received_at"])
    assert "quality_not_evaluated" in research_quality(rows[-1], old_metrics, at).reasons
