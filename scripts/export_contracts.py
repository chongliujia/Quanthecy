import argparse
import json
from pathlib import Path

from quanthecy_analytics.contracts.market import market_schema

parser = argparse.ArgumentParser(description="Export or check the shared market JSON Schema")
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
target = Path(__file__).resolve().parents[1] / "contracts/v1/market-observation.schema.json"
serialized = json.dumps(market_schema(), indent=2, sort_keys=True) + "\n"
if args.check:
    if not target.exists() or target.read_text() != serialized:
        raise SystemExit("Contract differs from its authoring model; run make contracts")
    print("Shared contract matches the authoring model.")
else:
    target.write_text(serialized)
