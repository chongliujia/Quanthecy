import io
import json
from typing import Any, Literal

import polars as pl


def export_observations(
    rows: list[dict[str, Any]], file_format: Literal["csv", "parquet"]
) -> bytes:
    schema = {
        "observation_id": pl.String,
        "platform": pl.String,
        "market_id": pl.String,
        "outcome_id": pl.String,
        "received_at": pl.String,
        "probability": pl.Float64,
        "best_bid": pl.Float64,
        "best_ask": pl.Float64,
        "volume": pl.Float64,
        "volume_unit": pl.String,
        "envelope_json": pl.String,
    }
    records = [
        {
            "observation_id": row["observation_id"],
            "platform": row["platform"],
            "market_id": row["market"]["id"],
            "outcome_id": row["outcome"]["id"],
            "received_at": row["received_at"],
            "probability": (row["probability"] or {}).get("value"),
            "best_bid": row["best_bid"],
            "best_ask": row["best_ask"],
            "volume": (row["volume"] or {}).get("value"),
            "volume_unit": (row["volume"] or {}).get("unit"),
            "envelope_json": json.dumps(
                row, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
        }
        for row in rows
    ]
    frame = pl.DataFrame(records, schema=schema)
    buffer = io.BytesIO()
    if file_format == "csv":
        frame.write_csv(buffer)
    else:
        frame.write_parquet(buffer, compression="zstd")
    return buffer.getvalue()
