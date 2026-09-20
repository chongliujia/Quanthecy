# Research data quality

The `research-quality-v2` policy distinguishes **price-change eligibility** from
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
  Precision-scale changes use the shared numerical policy below.
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

New signals use `rest-window-v3`, preserving research thresholds and applying the
same cumulative-volume tolerance to reset detection and rate calculations.
Their IDs differ from v1/v2; existing records are not overwritten. Metrics without the
current quality policy are marked pending until a new worker observation evaluates
them. Historical signal inputs can be reproduced with the recorded version:

```python
from quanthecy_analytics.signals import replay

metrics, signals = replay(saved_signal["version"], exported_observations)
```

`signals_v1.py` is frozen for existing v1 records. `signals_v2.py` and its independent
`quality_v1.py` preserve v2 behavior, including its strict counter-reset rule.
Unsupported versions fail explicitly.
Normal quality tests use synthetic fixtures and mocked providers, with no paid calls.

Updating the backend and analytics worker together keeps current quality gates in
sync. Other Python workers share those gates and should use the same image. Existing
metrics with the old policy remain ineligible until processed under v2; this change
does not rewrite stored observations, historical signals, reports or paper decisions.
No database migration or historical backfill is required.

## Cumulative-volume precision policy

For each adjacent pair of finite, nonnegative counters in the same units/basis:

```text
tolerance = max(1e-9, 8 * max(ulp(previous), ulp(current)))
delta = 0 if abs(current - previous) <= tolerance else current - previous
```

`ulp` is the spacing between adjacent binary64 values at the counter's magnitude.
Eight steps cover the four-step serialization discrepancy recorded in the
[September audit](data-quality-audit-2026-09-18.md). The absolute floor is in the
reported source units. This is a numerical policy, not a percentage-based allowance
for declining economic volume. Both constants are saved in v3 signal parameters.

Reset detection and interval rates call the same function. Both positive and
negative changes inside tolerance become zero, preventing rounding jitter from
creating a spurious activity baseline. Larger decreases still block volume
analysis; units/basis changes, missing/nonfinite values, and constant baselines
remain unavailable. A reset smaller than the numerical tolerance cannot be
distinguished from precision noise. Each comparison is local to an adjacent pair;
this does not repair counters or infer missing activity.

For example, `48732713.555604056 → 48732713.55560403` contributes zero activity;
a decline of `0.01` at the same scale still produces `volume_counter_reset`.
Original counter values and exported envelopes remain unchanged.

This policy does not add automatic history backfill, tick-complete collection,
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
