# Product scope

Status: planning baseline following the product discussion. This document records
the agreed direction; detailed contracts and thresholds remain implementation
work. It complements the architecture boundaries in [AGENTS.md](../AGENTS.md).

## Audience and purpose

Quanthecy primarily serves prediction-market traders and event-driven investors.
Traders need to monitor selected contracts, identify meaningful changes, and check
the data behind a signal. Investors need to follow events, compare contract rules,
review evidence, and revisit their research assumptions. Quantitative researchers
also need inspectable inputs and reproducible calculations.

These audiences share one research platform and organization model. The proposed
next iteration is described in [Trader and investor experience](trader-investor-experience.md);
its roadmap items are not claims of shipped functionality.

The main workflow is:

1. Discover an unusual market movement.
2. Inspect price, volume, spread, and data quality.
3. Compare an equivalent or related market on another platform.
4. Review relevant news, announcements, and their timing.
5. Read or request an Agent research report.
6. Export the observations and reproduce the deterministic analysis.

The three research modules below are all part of the MVP. Milestones describe
implementation order; completion of one module alone is not the complete MVP.

## Research modules

| Module | Initial capability | Initial coverage boundary |
| --- | --- | --- |
| Market activity | History, ranking, probability changes, volume anomalies, widening spreads | A configured set of markets on both exchanges; explicit collection coverage |
| Cross-platform comparison | Price differences, paired histories, visible rule differences | Manually reviewed pairs with recorded rationale and confidence |
| News and events | Source-linked items alongside market activity; inspectable market associations | A small configured set of news and announcement sources |

For cross-platform research, review question wording, outcomes, expiry, resolution
sources, settlement rules, and contract structure before accepting a match. Keep
equivalent contracts distinct from merely related markets. Differences in price
are research observations; an arbitrage claim requires a separate assessment of
rules, fees, and executable liquidity.

For event research, distinguish temporal association, a proposed explanation,
and an explanation supported by external evidence. Preserve conflicting evidence
and make uncertain market associations visible.

## Automated research

The MVP includes:

- Analysis triggered by deterministic signals.
- One scheduled daily research digest per enabled organization configuration.
- On-demand analysis of a selected market.
- Organization settings for market coverage, thresholds, cooldowns, schedules,
  and analysis budgets.
- An in-app research feed with evidence links and run status.

One Agent uses bounded, read-only research tools. Python computes numerical
metrics before the Agent interprets them. See [automated research](automated-research.md)
for the proposed execution design.

## Research data requirements

Before collector implementation, define a versioned contract covering:

- **Identity:** internal IDs and exchange identifiers for events, markets, and
  outcomes/contracts; relationships among them; outcome-specific observations.
- **Prices:** explicit price type, quote side, units, precision, and source;
  distinguish last trades, midpoints, bids, and asks.
- **Activity:** volume and liquidity definitions, units, and measurement windows.
- **Time:** source event time, first receipt time, persistence time, and UTC
  semantics; retain precision and indicate unavailable source timestamps.
- **Coverage:** collection start, gaps, stale observations, duplicates, and
  historical backfill provenance. Missing values remain explicit.
- **Lifecycle:** open and closed markets, resolution state, and versioned market
  rules. Research queries must be able to include closed markets.
- **Evidence:** stable references, original URLs, source publication time,
  first observation time, and document revisions with content hashes.

Historical news imported today must retain today's first observation time.
Point-in-time research must state whether it uses system-observed availability
or independently established historical availability; publication time alone
does not establish when the system knew an item.

Each metric and signal records its input window, observation references or
immutable dataset version, calculation version, parameters, and quality flags.
Versioned inputs must remain available for the advertised reproducibility period.
Declare any limits caused by source access or retention.

## Research access and presentation

Initial product views:

- Market explorer and market detail with history and collection coverage.
- Signal feed with trigger values, calculation windows, and quality indicators.
- Cross-platform comparison with reviewed match details.
- News/event timeline linking market observations to source evidence.
- Organization research feed, report detail, and daily digest.
- Workspace settings, basic watchlists, and automatic-analysis settings.

Readable summaries link to technical details. Historical APIs and CSV/Parquet
exports use the same metric definitions as the dashboard. An executable notebook
demonstrates reproducing one signal from a small exported dataset.

## Shared data and workspace data

Public market observations and platform-generated deterministic signals can be
shared across workspaces. Organization-owned resources include watchlists,
analysis settings, analysis jobs, Agent runs, digests, and usage records.

Customer-facing access to private research always includes an explicit
organization context and server-side authorization. Shared evidence does not
make organization prompts, configuration, reports, or usage public.

The first application migrations establish the custom UUID/email User,
Organization, and OrganizationMembership boundaries. Preserve organization
billing ownership for future work. Django Admin is the operator interface.

## Completion and later work

The MVP is complete when a user can follow the full research workflow on both
exchanges, inspect a reviewed comparison and a source-linked event timeline,
receive automatic analysis and a daily digest, and reproduce a signal from an
export. Deployment and recovery must meet the [roadmap](roadmap.md) checks.

Later enhancements include broad automatic market matching, larger source
coverage, advanced backtesting, richer tracking policies, and additional delivery
channels. Full billing, enterprise SSO, complex multi-Agent systems, and automatic
trading remain outside this MVP.

Before live integration, select the initial market universe, news sources,
historical coverage target, retention period, LLM provider, and operating budget.
These choices remain open; this document makes no live API availability claims.
