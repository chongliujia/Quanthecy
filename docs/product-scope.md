# Product scope

Status: product direction updated on 2026-09-17. The next development priority is
broad market data, opportunity discovery, and reproducible evaluation. Planned
capabilities below are not claims of shipped functionality; see the
[roadmap](roadmap.md) for implementation status. The architecture boundaries in
[AGENTS.md](../AGENTS.md) remain unchanged.

## Audience and purpose

Quanthecy serves prediction-market traders, investors, and quantitative researchers.
Its purpose is to use broad market data and external evidence to discover potential
pricing discrepancies and determine whether they offer a reproducible advantage
relative to contemporaneous market benchmarks, accounting for costs and liquidity.

Traders need timely candidates and inspectable quotes, depth, and activity.
Investors need event probabilities, contract rules, evidence, and conditions that
would change their assessment. Quantitative researchers need historical datasets,
features, replay, and evaluation. These are views over a shared research foundation.

These audiences share one platform and organization model. The
[trader and investor experience](trader-investor-experience.md) describes the
customer workflow; the roadmap sets the delivery order.

The main workflow is:

1. Discover markets and organize events and their related contracts.
2. Collect and align observations, rules, external evidence, and outcomes.
3. Scan for candidate discrepancies using explicit, versioned hypotheses.
4. Inspect supporting and conflicting evidence, quotes, costs, and data quality.
5. Use deterministic analysis and optional Agent interpretation to support a decision.
6. Track subsequent prices and settlement outcomes against the frozen candidate.
7. Reproduce and evaluate the method on independent events and later time periods.

An event and its related contracts are the central research unit. Research horizons
follow information arrival, contract structure, and lifecycle; the product does not
impose one short-term or long-term horizon across all categories. Forecast accuracy,
cost-adjusted returns, drawdown, and capital duration are distinct measurements.
An unusual price, high win rate, or valid Agent report alone does not establish an edge.

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

## Opportunity discovery and evaluation

The next iteration prioritizes three candidate families:

| Family | Research question | Required controls |
| --- | --- | --- |
| Related-contract consistency | Are threshold, mutually exclusive, or time-related contracts priced consistently? | Reviewed logical relationships, matching units/sources/times, completeness of outcome sets where required |
| Cross-platform discrepancies | Do equivalent outcomes have materially different quotes? | Reviewed settlement equivalence, synchronized quotes, available depth, and applicable costs |
| Event-information response | How do related prices respond after new information becomes available? | Publication and observation times, evidence revisions, association review, and comparable historical events |

Each family is a research hypothesis until evaluated. Conditional calibration by
category, price range, event horizon, and liquidity supplies a benchmark for
subsequent probability models. No universal price bias or profitable strategy is
assumed. Unsupported relationships or unavailable depth remain explicit limitations.

Save a candidate's detection time, event/contracts, hypothesis and version, input
references, available quotes, horizon, benchmark, costs/assumptions, and invalidation
conditions. Keep later outcomes separate from information available at detection.
Record unsuccessful candidates and excluded observations as well as successes.

Evaluation must distinguish probability forecasts from forecasts of subsequent
price movement. Compare probability forecasts with contemporaneous market forecasts
using calibration and proper scores; compare simulated trading outcomes using stated
entry/exit rules, spreads, fees, slippage, fills, and capital duration. Unknown
execution inputs cannot establish an executable return.

Use chronological development and held-out periods, group related contracts by
underlying event, and disclose sample counts, uncertainty, exclusions, and the
number of hypotheses tried. Repeated observations of one event are not independent
outcomes. Preserve a forward observation period after freezing the method. A
reproducible negative result is useful; evaluation infrastructure must not depend
on finding a positive return.

## Automated research

The planned automated workflow includes:

- Analysis triggered by deterministic signals.
- One scheduled daily research digest per enabled organization configuration.
- On-demand analysis of a selected market.
- Organization settings for market coverage, thresholds, cooldowns, schedules,
  and analysis budgets.
- An in-app research feed with evidence links and run status.

On-demand single-Agent and five-stage expert research already exist. Automatic
triggers and digests remain planned and follow the data and evaluation priorities.
Agents interpret evidence, propose hypotheses, and examine counterarguments;
Python computes metrics, replay, and evaluation. Model confidence is not a
calibrated probability or an independently validated edge. See
[automated research](automated-research.md) for the execution design.

## Research data requirements

Extend the existing versioned observation contract and repositories to cover:

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
- **Outcomes:** sourced settlement results and revisions, payout values, exceptional
  settlement states, and the time each result became available. Do not reconstruct
  labels from a final price alone.
- **Event relationships:** reviewed equivalence, implication, exclusivity, and
  temporal relationships, including their rule versions and validity periods.
- **Event timing:** distinguish scheduled and actual information releases, event
  occurrence, trading close, outcome determination, and payout when available.
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

Broaden discovery while collecting at different depths according to research need.
Track supported and excluded contract types, observed coverage, independent event
counts, history availability, spreads/depth, and sampling continuity by category.
Collection frequency must meet the selected method's requirements; a discovered
or collected market is not automatically eligible for every analysis. Validate
source access, history availability, and operating cost before increasing volume.

## Research access and presentation

Initial product views:

- Market explorer and market detail with history and collection coverage.
- Signal feed with trigger values, calculation windows, and quality indicators.
- Cross-platform comparison with reviewed match details.
- News/event timeline linking market observations to source evidence.
- Organization research feed, report detail, and daily digest.
- Workspace settings, basic watchlists, and automatic-analysis settings.
- Candidate opportunities with supporting/conflicting evidence, validation status,
  quote freshness, cost assumptions, and links to reproducible inputs and outcomes.
- Dataset exports and evaluation records for quantitative research.

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

The next milestone delivers a bounded, documented dataset; reproducible candidate
records; and an evaluation of a predeclared method against its benchmark, with
later observations tracked separately. The evaluation may find no usable edge.
Its purpose is to make that determination inspectable and repeatable.

The broader MVP combines this discovery/evaluation loop with the research workflow
on both exchanges, reviewed comparisons, source-linked timelines, and the planned
automatic research and digest workflow. Deployment and recovery must meet the
[roadmap](roadmap.md) checks.

Broad data coverage and a bounded replay/evaluation capability are near-term
priorities. Later enhancements include broad automatic semantic matching, more
advanced execution simulation, richer tracking policies, and additional delivery
channels. Full billing, enterprise SSO, and automatic trading remain outside this
MVP; further Agent complexity requires evidence of incremental research value.

For each expansion, record the market universe, source coverage, historical target,
retention, and operating budget. Choose initial research families using measured
data readiness and market characteristics. Existing macro/rates support provides a
starting sample, not evidence that this category offers the best opportunities.
