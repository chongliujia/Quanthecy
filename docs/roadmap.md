# Implementation roadmap

Status: milestones 1–3 are implemented; milestone 4 has an on-demand vertical
slice and milestone 5 has the research terminal. Remaining criteria are pending. See the
[foundation verification record](foundation.md), [market research implementation](market-research.md)
and [cross-platform/evidence guide](cross-market-evidence.md) for checks and limits.
Remaining acceptance criteria describe future work.

The complete MVP includes market activity, cross-platform comparison, news/event
research, and automated analysis. Earlier milestones provide usable intermediate
results. See [product scope](product-scope.md) and
[automated research](automated-research.md).

## 1. Application foundation and data contracts

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

## 2. Market history and deterministic signals

Implemented with bounded public REST snapshots, a durable collector journal,
explicit ClickHouse migrations, Redis current state, Django metadata/API, market
explorer/detail/history, rankings, three deterministic signal families and
CSV/Parquet reproduction. Live verification collected 10 markets per platform.
This milestone records sampling gaps; tick-complete WebSocket coverage, backfill
and historical rollups remain future extensions.

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

## 3. Cross-platform and news research

Implemented for selected macro/rates pairs and two official Federal Reserve feeds.
The research frontend now has overview, market, signal, comparison and evidence
routes, shareable detail links and cutoff views. Wider source coverage and automated
matching are future extensions. Automated associations remain explicitly unreviewed.

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

## 4. Automatic Agent research

Implemented subset: organization-scoped web model configuration, encrypted keys,
on-demand/test jobs, cutoff context, validated reports, cancellation, lease fencing,
and request/token limits. Models are disabled by default. See the
[terminal guide](research-terminal.md). Automated triggers, digests, and currency
budgets are still pending; the full acceptance criteria below are not yet met.

Deliver:

- Durable jobs for signal-triggered and on-demand analysis and daily digests.
- Single Agent with bounded evidence tools and validated structured reports.
- Organization watchlists/settings, thresholds, cooldowns, idempotency, schedules,
  retry policies, budget reservations, usage records, and run observability.
- In-app research feed, report details, evidence links, and failure/deferral states.

Acceptance: a signal produces a stored, evidence-linked report; repeated triggers
do not produce duplicate publications; a daily period produces one digest; failed
workers recover; concurrent jobs respect admission limits; tenant isolation holds.
Use mocked providers for normal tests and review a small evaluation set for factual
support and usefulness. Choose a provider and cost ceiling before any paid trial.

## 5. Integrated research workflow and deployment

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
