# Implementation roadmap

Status: updated on 2026-09-17. The original milestones 1–3 have bounded
implementations; milestone 4 has on-demand single/expert research and workspace
watchlists/alerts, and milestone 5 has the research terminal. Remaining criteria
are pending. See the
[foundation verification record](foundation.md), [market research implementation](market-research.md)
and [cross-platform/evidence guide](cross-market-evidence.md) for checks and limits.
Remaining acceptance criteria describe future work.

The next delivery sequence prioritizes market data, opportunity discovery, and
evaluation, as defined in [product scope](product-scope.md). The original numbered
milestones below remain a record of implemented foundations and outstanding work;
their numbering does not set the next delivery order. Automatic Agent triggers
and digests remain planned after the data and evaluation foundation.

## Next delivery sequence

All items in this section are planned. The target is an inspectable research
advantage for traders, investors, and quantitative researchers. Candidate counts,
data volume, win rates, and report counts alone are not evidence of that advantage.
Architecture and the research-only boundary remain unchanged.

### A. Establish research coverage and historical inputs

- Measure coverage by platform/category and independent event: lifecycle coverage,
  history depth, sampling gaps, quote quality, spreads/depth where available, and
  missing settlement outcomes. Distinguish directory entries from usable histories.
- Extend reviewed event/contract relationships and capture rules, sourced outcomes,
  revisions, and separate information-release, event, closing, and settlement times.
- Assess source access and backfill availability; preserve ingestion provenance and
  actual information availability. Record gaps and unavailable historical depth.
- Expand collection in tiers. Add trades and order-book capture for methods that
  require them, with sequence/recovery checks and bounded storage. Sampling cadence
  must satisfy the selected analytical window; increasing discovery alone does not
  make a market eligible.
- Define a versioned dataset manifest, retention, storage estimates, and reproducible
  exports. Include closed markets and failed/excluded observations in coverage
  accounting to expose selection effects.

Acceptance: a coverage report and reproducible dataset spanning selected events
on both exchanges, with documented exclusions, outcome provenance, timing semantics,
and measured collection/storage costs. Declare scope and quality thresholds before
acceptance; do not substitute a promised market count for usable research inputs.

### B. Discover and retain candidate opportunities

- Choose an initial method from related-contract consistency, cross-platform
  discrepancies, or event-information response using stage A measurements. Existing
  macro/rates support is a starting sample, not a fixed product specialization.
- Define the hypothesis, eligibility, horizon, benchmark, parameters, and invalidation
  conditions before evaluation. Candidate ranking must expose its components and
  cannot present anomaly magnitude as a probability of profit.
- Persist immutable detection inputs and method versions, with synchronized quotes,
  evidence references, relationship reviews, and cost/depth limitations. Preserve
  unsuccessful candidates and suppression reasons; deduplicate repeated detections.
- Reuse the terminal and alerts to inspect candidate evidence, counterarguments,
  validation status, and subsequent observations. Paid analysis remains explicitly
  configured; detecting a candidate does not itself authorize model requests.

Acceptance: replay produces the same candidates from the same dataset and method;
each candidate is inspectable at its detection cutoff. Tests exclude stale,
incompatible, or future-known inputs and verify any private workspace boundaries.

### C. Evaluate and observe the frozen method

Design the benchmark and sample split before tuning stage B. Implementation follows
the candidate records, but evaluation must not be retrofitted to successful examples.

- Use chronological development and held-out periods with event grouping, including
  cross-platform equivalents. Keep an experiment ledger of attempted methods and
  parameter choices; report sample size, exclusions, and uncertainty.
- Evaluate resolution probabilities against contemporaneous market probabilities
  using calibration and proper scoring rules. Treat future price-movement targets
  separately and align horizons with actual information/event times.
- For simulated returns, specify entry/exit rules, available bid/ask, depth, fills,
  fees, slippage, capital duration, and settlement exceptions. Report sensitivity to
  uncertain assumptions; unavailable execution inputs prevent executable-edge claims.
- Retain subsequent prices/outcomes separately from frozen detection inputs. Run
  the unchanged method prospectively and record successes, failures, and abstentions.
- Compare optional Agent assistance against the deterministic baseline for factual
  support, useful counterarguments, latency, and cost.

Acceptance: reproduce an evaluation report for at least one predeclared method,
including held-out results and a prospective observation record over a declared
period. Insufficient samples or no improvement are valid reported findings, not
reasons to hide results. Expand a method's scope only after reviewing its evidence
and operational cost. This milestone does not execute trades.

Reliability, tenant isolation, CI, and recovery work from milestone 5 accompany
these stages. Model scheduling, digests, and richer presentation build on the
validated data and candidate records rather than delaying their evaluation.

## Original implementation milestones

### 1. Application foundation and data contracts

Implemented. Both exchange contract fixtures are synthetic normalized examples;
real exchange parsing and source-specific semantic checks belong to milestone 2.

Deliver:

- Monorepo structure for React, Django, Rust ingestion, and Python analytics.
- Custom UUID/email User and manager, case-insensitive database email uniqueness,
  Organization, Membership, transactional personal workspace creation, and owner
  protection. Centralized organization authorization and Django Admin.
- Django Ninja versioned API, browser session/CSRF configuration, environment
  examples, migrations, health checks, and backend/worker process separation.
- Development and production Docker images with Compose configuration for
  PostgreSQL, ClickHouse, Redis, backend, worker, collector, and web.
- Versioned event/market/outcome, observation, timestamp, unit, quality, and
  provenance contracts; explicit ownership of metadata writes. Django owns
  PostgreSQL metadata reconciliation; Rust owns collection and normalization.

Acceptance: a documented Compose startup works from a clean checkout; initial
migrations and identity/tenant-isolation tests pass; container health and graceful
shutdown work. Representative sanitized fixtures exercise the data contract for
both exchanges before its first version is accepted.

### 2. Market history and deterministic signals

Implemented with bounded public REST snapshots, a durable collector journal,
explicit ClickHouse migrations, Redis current state, Django metadata/API, market
explorer/detail/history, rankings, three deterministic signal families and
CSV/Parquet reproduction. Live verification collected 10 markets per platform.
This milestone records sampling gaps. Subsequent work added bounded directory
discovery and collection tiers; see [market directory](market-directory.md).
WebSocket capture, backfill, and historical rollups remain unimplemented and are
assessed in stage A above according to the selected research requirements.

Deliver:

- Polymarket ingestion first, then Kalshi ingestion using the shared contract.
- Market discovery including lifecycle state, bounded collection coverage,
  normalization, deduplication, reconnect/gap handling, and batch persistence.
- Explicit ClickHouse schema migrations and Redis current state with TTLs.
- Market explorer/detail, historical API, rankings, initial probability-change,
  volume-anomaly, and spread-widening signals with versioned parameters.
- CSV/Parquet exports and one reproducible notebook example.

Acceptance: a selected market from each exchange is visible end to end; fixtures
cover malformed, duplicated, out-of-order, and missing data; interruption/recovery
preserves persisted history and reports unfilled gaps; a signal can be reproduced
from its exported inputs. Show collection start and available history explicitly.

### 3. Cross-platform and news research

Initially implemented for selected macro/rates pairs and two Federal Reserve feeds;
subsequent work added curated official/media sources, event dossiers, evidence
reviews, and revision differences. The research frontend has overview, market,
signal, comparison, event and evidence routes, shareable links and cutoff views.
Broad semantic matching remains future work. Automated associations remain
explicitly unreviewed; see [news sources](news-sources.md) and
[event evidence](event-evidence.md).

Deliver:

- Reviewed market-pair records with outcome alignment, match rationale, rule
  differences, confidence, review time, and revision history.
- Aligned price comparisons showing timestamp, quote type, freshness, and known
  comparability limits.
- Selected news/announcement adapters in the Python worker, evidence revisions,
  source links, publication/observation timestamps, and market associations.
- Comparison view and a market/news timeline using inspectable evidence.

Acceptance: demonstrate a reviewed pair and a source-linked timeline; incompatible
or stale quotes are visibly qualified or excluded; uncertain associations remain
visible; cutoff checks exclude evidence learned later. Document selected sources,
collection coverage, and evidence retention before live ingestion.

### 4. Automatic Agent research

Implemented subset: organization-scoped web model configuration, encrypted keys,
on-demand/test jobs, cutoff context, validated reports, cancellation, lease fencing,
and request/token limits. Single-Agent and five-stage expert workflows are available.
Workspace watchlists and deterministic in-app alerts are also implemented; those
alerts do not automatically invoke models. Models are disabled by default. See the
[terminal guide](research-terminal.md) and [watchlists/alerts](watchlists-alerts.md).
Automated triggers, digests, and currency budgets are still pending; the full
acceptance criteria below are not yet met.

Deliver:

- Durable jobs for signal-triggered and on-demand analysis and daily digests.
- Bounded Agent research with validated structured reports; evaluate the incremental
  value of the existing expert workflow against single-Agent research.
- Organization watchlists/settings, thresholds, cooldowns, idempotency, schedules,
  retry policies, budget reservations, usage records, and run observability.
- In-app research feed, report details, evidence links, and failure/deferral states.

Acceptance: a signal produces a stored, evidence-linked report; repeated triggers
do not produce duplicate publications; a daily period produces one digest; failed
workers recover; concurrent jobs respect admission limits; tenant isolation holds.
Use mocked providers for normal tests and review a small evaluation set for factual
support and usefulness. Choose a provider and cost ceiling before any paid trial.

### 5. Integrated research workflow and deployment

Deliver:

- A walkthrough covering discovery, historical inspection, cross-platform
  comparison, news evidence, automated research, and export/reproduction.
- Loading, empty, stale-data, error, organization-switching, and accessibility
  behavior for the core views.
- CI for relevant formatting, lint, type checks, meaningful tests, migration
  consistency, frontend build, and production image builds.
- Single-server deployment instructions, restricted infrastructure exposure,
  persistent volumes, backup/restore steps, source/model failure handling, and
  operational metrics.
- README setup commands and sample outputs verified against the implementation.

Acceptance: complete the walkthrough on the documented Compose deployment;
exercise restart, source/model outage, and backup restoration; verify historical
coverage and private research survive as documented. Record actual performance
and operating cost from the chosen workload before expanding coverage.

## Decisions needed during implementation

Select the initial market universe and collection depth, historical/backfill
targets, news sources, evidence/history retention, initial signal parameters,
model/provider, and operating budget. Validate current exchange/source APIs before
implementing their adapters. Dates, scale claims, provider guarantees, and numeric
defaults are intentionally not committed in this roadmap.
