# Trader and investor experience

Status: first implementation delivered, 2026-09-17. Collection diagnostics and
workspace watchlists with sampled in-app alerts are implemented; see the
[usage and evaluation guide](watchlists-alerts.md). Evidence/thesis features, layout
presets and deeper microstructure below remain proposed. This brief extends [product scope](product-scope.md) and
preserves the architecture and research-only boundary in [AGENTS.md](../AGENTS.md).

## Product direction

Quanthecy should help prediction-market traders and event-driven investors answer:

1. Which of my markets changed enough to deserve attention?
2. What changed in the price, contract, or available evidence?
3. What supports or contradicts my explanation?
4. Which future observation would change my view?

The daily workflow is **watch → detect → inspect → record → revisit**. A reusable
watchlist and a reliable reminder are more valuable at this stage than additional
unconnected dashboard pages. The proposed positioning is an evidence-driven
prediction-market research terminal. No profitability or execution claim follows
from a signal, a price difference, or an Agent report.

## Existing foundation and data limits

| Available foundation | What it supports next | Boundary |
| --- | --- | --- |
| Selected-market REST observations and historical charts | Watchlists, sampled price-change and spread alerts | Target cadence is about 60 seconds; gaps remain visible |
| Deterministic signals with saved inputs and thresholds | Explainable, reproducible alert details | Missing or stale inputs cannot become zero or a valid trigger |
| Versioned evidence and event relevance review | Evidence-change feed and event dossiers | Topic matches do not establish causation or reviewed relevance |
| Reviewed cross-platform comparisons | Side-by-side rule and quote inspection | A quote difference is not executable arbitrage |
| On-demand Agent research and frozen context | Short research briefs with linked evidence | Model confidence is not calibrated event probability |
| Organization membership and Django operations console | Private watchlists, alert rules, and research notes | Staff access and customer workspace authorization remain separate |

Implementation references: [market research](market-research.md),
[collection coverage](collection-coverage.md), and [research terminal](research-terminal.md).
There is no complete tick history, trade/depth capture, or historical backfill in
the current market-research slice. Screens must not imply those capabilities.

## Delivery order

### 0. Make collection state understandable

The existing admin can configure collection targets, topics, and evidence sources.
That configuration does not start a stopped container. Improve operator visibility
before relying on alerts:

- Distinguish requested pause, pending configuration, missing worker heartbeat,
  repeated source failures, and stale observations.
- Show the requested and applied configuration revisions, last successful
  collection, latest valid observation, and the affected market count.
- Keep configuration acknowledgment distinct from successful data collection.
- Show the same freshness semantics in the customer terminal. A source-level
  healthy state must not hide stale individual contracts.
- Document service recovery through the deployment operator. Any future service
  control integration needs a separate design; do not expose the Docker socket to
  the web application.

Acceptance: intentional pause and stopped service have different explanations;
failed or stale sources do not appear live; recovery is confirmed by advancing
valid observations rather than a green container alone.

### 1. Watchlists, scanner, and in-app alerts

Implemented first customer-facing slice; remaining acceptance work includes
operational alert latency measurement under sustained live collection.

- Create, rename and archive workspace watchlists; reorder or remove their markets. Adding a contract to a
  watchlist does not silently expand the platform's collection universe; show
  uncollected, stale, and closed states.
- Filter the scanner to a list. Keep explicit platform, outcome, price basis,
  price change in percentage points, spread, age, and collection coverage.
- Begin with sampled probability-change and spread rules. Configure a window,
  threshold, enabled state, and cooldown. Use server-side deterministic metrics.
- Keep alerts in an in-app inbox with unread/read state and a direct link to the
  selected contract, trigger window, calculation version, and saved input values.
- Evaluate each new eligible observation/window once. Deduplicate across worker
  restarts and use a documented re-arm rule so a sustained condition does not
  produce a notification every minute. Do not assume a threshold crossing
  occurred between two samples.
- Suppress market triggers for stale or insufficient data, retain an explicit
  evaluation status, and provide a separate collection-status notice.
- Keep model requests user initiated in this release. Alert creation must not
  silently enable paid Agent runs or external notification delivery.

Acceptance: a user can save a market, define a rule, inspect a fixture-triggered
alert, and open its evidence without leaving the terminal. Tests cover tenant
isolation, read-only roles, duplicate suppression, re-arm/cooldown, restart
recovery, stale inputs, and disabled rules. Alert latency is measured relative to
an eligible collected observation; minute polling is not marketed as tick-level.

### 2. Evidence changes and research theses

Build the distinctive research workflow on the first release:

- Compare document revisions and show what became available since the user's
  previous research cutoff. Preserve publication, first-observation, and revision
  times as separate fields.
- Distinguish a new source item, a revised source item, and a changed human review.
  Alert on those recorded facts first. An Agent's interpretation of a contradiction
  remains a cited hypothesis, not an automatically established fact.
- Present one short research brief: **what changed / supporting evidence /
  counter-evidence / unresolved questions / next catalyst**. Expand to the full
  report and frozen references on demand.
- Record a workspace thesis with its assumptions, evidence references, date,
  horizon, and explicit invalidation conditions. Keep revision history.
- Link events, contracts, source versions, and thesis assumptions using typed,
  provenance-bearing relationships. Start with these relational records before
  choosing a separate graph database or a graph visualization.
- Offer a rule comparison for reviewed contract pairs. Show changed settlement
  language and invalidate outdated equivalence reviews.

Acceptance: a user can trace a reported change to two versions, inspect a
counterargument, and see which assumption requires review. Point-in-time views
must exclude evidence unavailable to the system at that cutoff. Deletions or
retention gaps must be reported rather than silently reconstructing missing data.

### 3. Deeper market microstructure and evaluation

Gate these features on measured data readiness:

- Order-book depth, trade prints, imbalance, and fast alerts require Rust ingestion,
  sequence/reconnect handling, timestamp semantics, replay tests, and gap tracking.
- Related-outcome probability checks require a reviewed definition of a complete,
  mutually exclusive event group and compatible observation times. An arbitrary
  group of related contracts need not sum to 100%.
- Scenario analysis and exposure grouping require versioned contract relationships.
  A manual research portfolio should clearly separate user-entered positions from
  verified exchange balances, and account for fees and resolution rules.
- Forecast calibration, historical replay, and backtests need resolved outcomes,
  point-in-time evidence, sufficient retained history, and stated sample selection.
  Report out-of-sample calibration and coverage, not only successful examples.

## Layout and visual direction

Keep one application with two layout presets; switching preserves the selected
contract, active workspace, watchlist, and research cutoff.

| Region | Monitor preset | Research preset |
| --- | --- | --- |
| Top bar | Workspace, search, layout, language/theme, collection status | Same controls and state |
| Narrow navigation | Workspace, markets, signals, evidence, settings | Same destinations |
| Main canvas | Selected contract, compact quote strip, probability chart | Event scope, reviewed evidence, changes and contract rules |
| Right dock | Watchlist and compact contract/evidence detail | Watchlist and thesis/assumptions |
| Bottom panel | Alerts, signals, news changes | Research history, evidence changes, notes |

Replace the large in-app overview hero with the user's watchlist, unread changes,
and upcoming recorded catalysts. Keep project introductions in public docs and
onboarding. Counts alone should not dominate the daily workspace.

Desktop layout requirements:

- At 1280×720 and 1440×900, keep navigation, quote context, and the primary chart or
  research canvas visible without whole-page vertical scrolling. Long lists and
  report contents scroll within their own panels.
- Use the existing resizable right dock and bottom panel; remember preferences per
  user outside the identity model. Offer collapse and restore controls.
- Aim for 13px body/table text and 12px secondary labels with tabular numerals.
  Preserve readable report text, browser zoom, and a comfortable-density option.
- Use neutral surfaces, restrained teal selection, and semantic change colors with
  explicit signs/labels. Avoid blinking prices and unrelated decorative charts.
- Show outcome and quote basis near the number; use `%` for price-implied
  probability and `pp` for changes. Keep bid and ask visible where available.
- Keep core controls usable with keyboard and visible focus. If chart shortcuts
  are introduced, do not intercept keys while a user edits text.
- On narrow screens and at high zoom, use a focused single panel and deliberate
  tab navigation instead of shrinking a desktop grid into unreadable columns.
- Maintain English/Chinese parity and light/dark themes for every new surface.

## Implementation boundaries

Watchlists, alert definitions, delivery/read state, and theses are organization-
scoped PostgreSQL resources accessed through Django services and Ninja schemas.
Use UUIDs, explicit authorization, migrations, and Django Admin where appropriate.
User-specific unread markers and preferences also include the user identity.

The analytics worker evaluates normalized metrics and records idempotent trigger
events. ClickHouse retains analytical inputs; Redis may coordinate work but must
not be the only durable alert record. React consumes application APIs. Agent
research consumes bounded, versioned context after deterministic computation.

## Product validation

Run a small usability study with event-driven traders and investors. Measure time
to locate a changed watched contract, explain a trigger, inspect its source, and
record a revised thesis. Also measure alert duplication, stale-data suppression,
coverage, and source-to-alert delay. Set launch targets after a baseline is measured.
User retention and research usefulness matter more than the number of panels or
Agent roles. Avoid choosing success metrics based solely on simulated returns.

## Reference patterns

TradingView connects [watchlists to screening](https://www.tradingview.com/support/solutions/43000724549-how-to-scan-watchlist-or-flagged-list/)
and supports [per-symbol conditions across a watchlist](https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/).
These are workflow references, not dependencies or claims of feature parity.
Quanthecy's proposed differentiation is evidence provenance, event/contract
semantics, and tracking changes to a research thesis.
