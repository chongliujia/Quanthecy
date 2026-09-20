"""Full-output hashes captured from v2 before the precision policy changed."""

import hashlib
import json
from pathlib import Path

import pytest
from quanthecy_analytics.signals import replay


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("normal", "7f310b16e854cd666dc927f69a91976a505eebd0ce36fca6fc65a6d0a1437fae"),
        ("reset", "8411b49623bb44f81880fea969c7136514a5c28556e808b9d9ca3ee2c3d02909"),
        ("unit", "75fd37f1759f65a7a152b568da663bf483d91d39dffe825a0d368c01ba3dcac2"),
        ("constant", "fde452771f6d6029d634d991cfd901e5f4259e585731bd49774986d466b2cfd5"),
        ("missing", "66337e12c7dc742bd860b1d98edc19a29634931486df5f63c492b7648bb9de4e"),
        ("invalid", "9bab53f557ac39de3dd1aa7304031a8fe86a8a4cddcb9a643db5594f62df61c5"),
        ("gap", "226b0fb4fbd37857cd9fc2e949aa00b88ed48e0741617f065d275dad595b6b3d"),
        ("empty", "4147056690749f198cab8ea3d72bf30a92b80edf1d14d6d23603457b213dcc54"),
    ],
)
def test_v2_replay_preserves_saved_ids_parameters_metrics_and_quality(scenario, expected):
    rows = json.loads((Path(__file__).parent / "fixtures/research-window.json").read_text())
    if scenario == "reset":
        rows[-1]["volume"]["value"] = 0
    elif scenario == "unit":
        rows[6]["volume"]["unit"] = "CONTRACTS"
    elif scenario == "constant":
        for row in rows:
            row["volume"]["value"] = 100
    elif scenario == "missing":
        rows[6]["volume"] = None
    elif scenario == "invalid":
        rows[6]["probability"]["value"] = 0.99
    elif scenario == "gap":
        rows[5]["quality_flags"].append("GAP")
    elif scenario == "empty":
        rows = []
    output = replay("rest-window-v2", rows)
    assert hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest() == expected
