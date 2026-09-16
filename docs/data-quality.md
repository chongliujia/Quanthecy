# Research data quality

The `research-quality-v1` policy distinguishes **price-change eligibility** from
**volume-anomaly eligibility**. A market can have both, one, or neither available.
These labels describe the sampled data, not forecast accuracy, representativeness,
liquidity, or a trading opportunity. Collection health alone is not eligibility.

## Checks and behavior

- A 15-minute continuous window requires at least 10 unique observations, a sample
  at/before the boundary within 150 seconds, and no interval over 150 seconds.
- Market, outcome, and settlement-rule version must remain consistent. Closed
  markets, missing rules, and GAP / OUT_OF_ORDER / STALE / CROSSED_BOOK
  flags prevent both indicator families.
- PARTIAL from a missing quote or volume blocks that indicator only. Missing rules
  or an unexplained PARTIAL flag block both. Comparisons retain their stricter
  existing exclusion of any PARTIAL observation.
- Identical observation retries are deduplicated. Different content under one ID
  prevents calculation. A truncated history query cannot produce signals.
- Price-change research requires finite midpoint values, valid interior two-sided
  quotes, bid ≤ ask, midpoint agreement within 1e-9, one source and valid as-of times.
  Missing prices never become zero. Comparisons also reject inconsistent midpoints.
- Volume research requires nonnegative cumulative values with stable units/basis,
  valid as-of times and no counter reset. Constant baseline activity has no defined
  Z score: volume anomaly is unavailable, while valid price changes remain usable.
- Recording time cannot precede receipt. Current eligibility rejects future data
  and observations or indicator as-of times older than 180 seconds at the requested
  research cutoff. Stored historical signals remain historical records.
- A live quote with a different observation ID cannot inherit a processed window's
  quality status. It is shown as awaiting analytics until the worker catches up.
- Exchange quote timestamps and liquidity depth remain unavailable for current
  REST adapters. Receipt/as-of checks cannot establish when an exchange's underlying
  quote last changed. Those limitations remain visible even when checks pass.

Checks run in deterministic Python analytics; HTTP views read the persisted result
and apply current freshness. Rust retains ingestion and normalization ownership.
The ingestion worker requests at most 1,001 rows and refuses a window exceeding
1,000; it constrains inputs to those recorded by the observation's recorded time.

Agent context `context-v3` includes the same quality result. Conditional forecasts
require an eligible price window in addition to the existing evidence, open-market,
rules and future-close gates. Review of limitations remains possible when forecasting
is unavailable. No new automatic model calls are introduced.

## Operator and user surfaces

Operators with `operations.view_collection_status` can open **Data quality / 数据质量**
in Django Admin. The page shows counts, per-market reasons, known limitations,
platform/title/status filters and pagination. It evaluates at most the latest 1,000
matching market records and explicitly labels truncated coverage; issue counts can
overlap. An empty sample does not establish quality. Invalid stored structures fail
closed in this view. It does not scan ClickHouse history on every page request.

Market list/detail APIs expose `data_quality`; market detail displays a bilingual,
expandable explanation. Rankings require the current policy and eligible metrics.
Closed or stale history remains available for inspection and reproduction.

## Versioning and rollout

New signals use `rest-window-v2`, preserving thresholds but adding semantic checks.
Their IDs differ from v1; existing records are not overwritten. Metrics without the
current quality policy are marked pending until a new worker observation evaluates
them. Historical signal inputs can be reproduced with the recorded version:

```python
from quanthecy_analytics.signals import replay

metrics, signals = replay(saved_signal["version"], exported_observations)
```

`signals_v1.py` is frozen for existing v1 records. Unsupported versions fail explicitly.
Normal quality tests use synthetic fixtures and mocked providers, with no paid calls.

This first policy does not add automatic history backfill, tick-complete collection,
external source verification, a quarantine queue, or topic-based market selection.
Those require separate ingestion and operations work; no claim of complete or
error-free exchange data is made.

## Verification — 16 September 2026

- 206 Python/Django tests passed, including three real ClickHouse checks against
  unique disposable test databases. Fixtures verify field-specific partial-data
  eligibility, semantic quote consistency, counter resets, truncated histories,
  conflicting duplicates, freshness, future timestamps, cache/window alignment,
  historical replay, operator permissions and Agent forecast exclusion.
- 40 frontend tests passed. Ruff, formatting, mypy, ESLint, TypeScript/production
  builds and migration consistency checks passed.
- Local production containers were updated. Browser checks verified actual
  per-market findings, status filtering, Chinese/English, responsive administration
  and the expandable market-quality explanation. No paid model calls were made.

Topic-scoped collection coverage and operator controls are documented in [collection-coverage.md](collection-coverage.md).
