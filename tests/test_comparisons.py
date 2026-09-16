import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from quanthecy_analytics.comparisons import aligned_history, compare, timestamp


@pytest.fixture
def sample():
    row = json.loads((Path(__file__).parent / "fixtures/research-window.json").read_text())[-1]
    row["quality_flags"] = ["SOURCE_TIME_MISSING"]
    row["recorded_at"] = row["received_at"]
    right = copy.deepcopy(row)
    right["probability"]["value"] = 0.2
    right["best_bid"], right["best_ask"] = 0.19, 0.21
    review = dict(
        version=1,
        relation="RELATED",
        alignment="SAME",
        reviewed_at=timestamp(row["received_at"]),
        left_snapshot=copy.deepcopy(row),
        right_snapshot=copy.deepcopy(right),
    )
    return row, right, review, timestamp(row["received_at"])


def test_complement_alignment_transforms_probability_and_book(sample):
    left, right, review, at = sample
    review["alignment"] = "COMPLEMENT"
    point = compare(left, right, review, at)
    assert point["right"]["probability"] == pytest.approx(0.8)
    assert point["right"]["bid"] == pytest.approx(0.79)
    assert point["right"]["ask"] == pytest.approx(0.81)
    assert point["difference"] == pytest.approx(left["probability"]["value"] - 0.8)
    assert point["right"]["observation_id"] == right["observation_id"]


@pytest.mark.parametrize(
    "case,issue",
    [
        ("stale", "LEFT_STALE"),
        ("skew", "OBSERVATION_SKEW"),
        ("rules", "LEFT_REVIEW_OUTDATED"),
        ("outcome", "LEFT_OUTCOME_MISMATCH"),
        ("gap", "LEFT_QUALITY_EXCLUDED"),
        ("closed", "LEFT_CLOSED"),
        ("basis", "BASIS_MISMATCH"),
        ("missing", "LEFT_NO_PRICE"),
        ("incompatible", "INCOMPATIBLE_RULES"),
    ],
)
def test_unqualified_comparisons_never_produce_a_difference(sample, case, issue):
    left, right, review, at = sample
    if case == "stale":
        at += timedelta(seconds=181)
    if case == "skew":
        left["received_at"] = (at - timedelta(seconds=91)).isoformat()
    if case == "rules":
        left["market"]["rules_version"] = "new-rules"
    if case == "outcome":
        left["outcome"]["id"] = "wrong-outcome"
    if case == "gap":
        left["quality_flags"].append("GAP")
    if case == "closed":
        left["market"]["status"] = "CLOSED"
    if case == "basis":
        left["probability"]["basis"] = "LAST_TRADE"
    if case == "missing":
        left["probability"] = None
    if case == "incompatible":
        review["relation"] = "INCOMPATIBLE"
    point = compare(left, right, review, at)
    assert point["difference"] is None
    assert issue in point["issues"]


def test_alignment_never_uses_future_records_or_later_reviews(sample):
    left, right, review, at = sample
    left["recorded_at"] = (at + timedelta(seconds=30)).isoformat()
    review["reviewed_at"] = at + timedelta(seconds=60)
    points = aligned_history(
        [left], [right], [review], [at, at + timedelta(seconds=30), at + timedelta(seconds=60)]
    )
    assert points[0]["left"] is None
    assert "NO_REVIEW_AT_TIME" in points[1]["issues"]
    assert points[2]["difference"] is not None


def test_late_arriving_old_sample_does_not_overwrite_newer_sample(sample):
    left, right, review, at = sample
    old = copy.deepcopy(left)
    old["received_at"] = (at - timedelta(seconds=60)).isoformat()
    old["recorded_at"] = (at + timedelta(seconds=30)).isoformat()
    old["observation_id"] = "late-old-sample"
    points = aligned_history([old, left], [right], [review], [at, at + timedelta(seconds=30)])
    assert all(p["left"]["observation_id"] == left["observation_id"] for p in points)
