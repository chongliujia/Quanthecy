# Market observation contract v1

The authoring model is `python/quanthecy_analytics/contracts/market.py`.
`make contracts` exports its JSON Schema; `make check-contracts` detects drift.
Rust consumes that checked-in schema with format validation enabled. Python's
`validate_observation` applies the same schema before constructing its typed model.
Both runtimes reject unknown fields, numeric strings, non-finite numbers, invalid
UUIDs/dates, non-UTC wire timestamps, and probabilities outside `[0, 1]`.

Each observation describes **one outcome of one market within one event**. The
nested relationship is authoritative for this envelope. Multiple outcome records
may reference the same market; never combine outcome prices without explicit
semantics. Exchange identifiers are opaque and namespaced by `platform`; internal
UUIDs are stable mappings, never regenerated on each observation. Metadata mapping
and reconciliation are owned by Django. The collector handoff now uses the
published `identity/v1` UUIDv5 protocol described in
[market research](../docs/market-research.md).

Prices are normalized to a unit payout in USD and lie in `[0, 1]`. Each selected
probability records its basis, source, and own observation time. Quotes are for the
named outcome. A missing quote is null. An adapter must not imply that a trade and
a quote were observed together when their source timestamps differ: emit separate
observations with the relevant null fields. Volume and liquidity have independent
units, a named calculation/source basis, and a timestamp. A null activity window
start denotes a source-defined cumulative measure or point-in-time estimate; its
basis must explain which. Analytics must not treat USD and contract quantities as
interchangeable. Precision-critical billing/settlement data is outside this wire
contract and requires exact decimal representation.

`event_at` records source event time when available, `received_at` first system
receipt, and `recorded_at` the durable observation time. All wire timestamps are UTC
with a `Z` suffix and up to microsecond precision. Keep source/receipt times through
backfills and replay. `observation_id` and `payload_sha256` support traceability;
neither alone defines the future exchange-specific deduplication algorithm.

Crossed books and late events can be retained with explicit quality flags. Shape
validation does not prove correct identity mapping, units, quote consistency, rule
versions, source authenticity, or data completeness. Source adapters implement
additional semantic checks described in the market research guide. Rules can be empty
only when unknown and accompanied by `PARTIAL`; analytical eligibility checks must
exclude observations missing required context.

The `observation.json` fixtures in `tests/fixtures/{polymarket,kalshi}` are **synthetic
normalized examples** with fictitious market names/IDs. `market-rest.json` contains
reduced public source responses captured on 2026-09-15. The separate
`research-window.json` is synthetic and used only for calculation reproduction.
Breaking wire changes
require a new version, fixtures, and an explicit compatibility/migration decision.
