# Paper trading lab — paper-v1

This page documents the preserved v1 policy. New experiments default to [v2 automatic entry reviews](paper-trading-v2.md); v1 remains available as historical evidence.

The lab runs prospective simulations against public Polymarket and Kalshi data. It never submits an exchange order, holds exchange credentials, signs transactions, or moves money. This explicitly requested extension evaluates research signals; it does not change Quanthecy's research-first architecture or enable live autonomous trading.

Open **模拟交易实验室 / Paper trading lab** at `/#/paper`, select a workspace and start an experiment. OWNER, ADMIN and MEMBER may create, pause and resume; VIEWER may read. Each workspace has one immutable experiment and each selected platform has three independent accounts, initially USD 10,000 each by default (user configurable before creation). A flat cash benchmark accompanies the chart. Accounts are independent counterfactuals: their fills do not compete with one another. Capital is not transferred between platforms.

## Frozen policy

Choose at most 20 markets from the currently fresh, two-sided priority collection universe. Candidate selection prefers usable price history, then probability near 50%, limits each platform to 10 markets, and includes at most one contract per exchange event. This is an explicit experimental selection policy, not a representative sample of all markets or a claim about profitability. Selection and contract rules versions are frozen at creation. No replacement of failed or resolved markets takes place during the experiment.

- **Momentum:** buy long YES when the stored, quality-approved 15-minute probability change is at least 2 percentage points. Evaluate each market no more often than every five minutes and once per observation. Exit after one hour, or when valid momentum is non-positive. After closing a position, wait 15 minutes before re-entry.
- **Momentum + Agent filter:** use exactly the same numerical rules, then require this workspace's latest successful RESEARCH report, completed and cut off within the preceding 24 hours. Only WATCH or INVESTIGATE with no risk flags allows entry. Missing reports mean abstention. Confidence is never interpreted as win probability. This version reuses existing reports and does not automatically schedule model calls; report availability therefore influences the comparison.
- **Buy and hold:** one initial YES purchase per market, held until verified binary settlement. Failed or partial initial orders are subject to the same five-minute decision interval; once a position has been opened and closed it is not repurchased.
- Maximum order budget: 1% of the account's initial capital. Maximum cost plus pending buy reservations per exchange event: 2%. Orders request whole shares, capped at 2,000 shares per buy. No shorting, leverage, compounding of order size or cross-platform arbitrage. Do not enter within one hour of the known close time.

Each account keeps available cash, pending reservations, positions, realized P&L, fees, and minute-level equity observations. Stored evidence includes the observation, deterministic metrics, Agent report if used, configuration version and the execution quote. Order details recompute simulated fills from those frozen inputs and compare quantity, price and fee with the ledger.

## Execution and valuation

The Rust collector reads public order books for the shared execution universe, with at least 15 seconds between completed cycles. It refreshes market and fee metadata every 60 seconds, respects source collection switches and writes quotes to a separate durable spool before ClickHouse. The universe is globally capped at 20 distinct contracts; the worker is capped at 100 experiments. Paused experiments retain collection capacity while they have positions. Limits are enforced under the existing global collection-plan database lock.

An order cannot fill from its decision quote. Only a newly acquired eligible book at least two seconds after the decision may fill it. It expires after 120 seconds. Quotes older than 90 seconds, future receipt/persistence times, metadata older than 120 seconds, unavailable fees, missing sides, or a spread above 8 cents block execution. Acquisition time represents receipt of a public REST response; exchange book timestamps may represent the last modification and are retained separately. This is a snapshot simulation, not a reconstruction of the exchange matching engine.

A single IOC simulation takes at most 10% of each displayed price level, rounds quantities down to whole shares, and adds 10 basis points of adverse relative slippage. Buy limits allow 50 basis points above the decision ask; sell limits allow 200 basis points below the decision bid. Unfilled remainders are canceled. Cash reservations include estimated fees, and actual simulation cannot exceed available cash. Missing depth never produces a fabricated fill. This version does not model queue position, hidden liquidity, exchange order minimums, tick-size rounding of the simulated slippage, rebates, or market impact beyond the depth cap and fixed slippage.

Fee parameters are read from public exchange metadata and retained with each quote. Polymarket supports an explicit disabled-fees flag, or `feeSchedule` with exponent 1 and a known rate. Kalshi supports `quadratic` / `quadratic_with_maker_fees` and a known series multiplier. Unknown or unsupported schedules block fills. Fees are approximated per simulated price-level fill: Polymarket rounded to five decimals; Kalshi rounded up to cents. Actual venue aggregation and rounding can differ. Sources: [Polymarket market details](https://docs.polymarket.com/market-data/market-details), [Polymarket fees](https://docs.polymarket.com/trading/fees), [Kalshi fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf).

Equity estimates immediate liquidation at bids using the same depth cap, adverse slippage and exit fees. If any position cannot be fully priced, the entire account's equity and unrealized P&L for that sample are null. The chart has a gap, not a zero. Maximum drawdown uses available minute-level equity samples only and can miss intraminute or unpriced drawdowns. The UI displays the most recent 720 samples; older observations remain in PostgreSQL. Cash is not increased by marking a position up.

Kalshi settlement requires `finalized` and an explicit yes/no result. Polymarket settlement requires Gamma's closed/resolved state and a matching closed CLOB condition with exactly one binary winning token. Token identity and Yes/No outcomes must match. A 404, conflicting status, unavailable winner, void/fractional payout, or other unsupported settlement remains unresolved. Prices alone never establish settlement. A verified payout is applied once under the account transaction; positions, ledger and cash are updated together. Raw source evidence is retained in ClickHouse.

Pausing cancels pending orders and stops new decisions. It does not liquidate existing positions: valuations and verified settlements continue. Closing the browser does not stop the worker. The experiment cannot be silently reset to conceal losses.

## Architecture and operation

- **Rust Data Plane:** `services/market-data/src/execution.rs` reads public books/fee metadata, normalizes YES bids/asks and settlement, journals immutable quote IDs, retries durable batches and reports collection telemetry. No exchange execution API exists in this module.
- **ClickHouse:** explicit `0003_execution_quotes.sql` migration, `ReplacingMergeTree` with stable quote IDs; historical execution evidence is independent of Redis.
- **Django / PostgreSQL:** `quanthecy.paper` owns organization-scoped experiments, accounts, decisions, orders, positions, append-only ledger and equity observations. UUIDs identify customer-visible entities. The experiment row is locked for every account-processing transaction; concurrent workers skip locked experiments. API handlers call services and return explicit Ninja schemas.
- **Python analytics:** `quanthecy_analytics.paper` computes fills, fees and validation using Decimal arithmetic. `paper-worker` fetches immutable analytical quotes outside the account transaction, then processes each experiment atomically. No model or exchange calls run in HTTP handlers.
- **Redis:** short-lived execution-universe and telemetry keys expire after 90 seconds. PostgreSQL and ClickHouse remain authoritative.
- **React:** authenticated same-origin Django API, explicit organization paths, session/CSRF protection, bilingual UI, independent platform balances and fill audit dialog.

Deploy with the normal Compose migration job before starting `paper-worker`. For an existing local deployment:

```sh
docker compose build backend web market-data
docker compose run --rm migrate
docker compose up -d backend worker paper-worker market-data web
```

The migration job applies both Django and analytical schema migrations. Health checks cover the worker heartbeat. Check the experiment's `checked_at` and `error_code` as well as the collector telemetry: a worker process can be alive while a particular experiment fails. A stopped collector produces stale/absent quotes and abstentions, rather than inferred fills. Candidate selection depends on the existing priority collection plan; collection frequency must support its freshness threshold.

The lab is a forward observation tool. Early fee/spread losses, a flat account or missing reports are valid results. It is not a historical backtest, an exchange sandbox account, a reliable estimate of future returns, or a basis for an automatic transition to real funds.

## Local verification — 2026-09-18

The local Personal Workspace experiment was started with 10 Polymarket and 10 Kalshi markets and six independent USD 10,000 virtual accounts. At 03:54 UTC, all 20 execution books were being collected successfully. The buy-and-hold accounts had 20 simulated orders: nine full fills and eleven partial fills. All 20 replay checks matched; each account satisfied both `sum(ledger.cash_delta) = cash` and `cash + position_cost_basis - initial_cash = realized_pnl`. Restarting the paper worker retained all positions and produced no duplicate fills.

At that initial snapshot, estimated liquidation equity was USD 9,952.952664 for Polymarket buy-and-hold and USD 9,946.534580 for Kalshi buy-and-hold, including modeled exit costs. These immediate marks reflect spreads, fees, slippage and current books; they are not evidence of a strategy's long-run return. Both momentum variants remained in cash because the numerical entry threshold had not been reached.

Validation completed: 393 regular Python tests, five opt-in real-ClickHouse integration tests (including execution-quote deduplication and future-data exclusion), 87 frontend tests and 22 Rust tests. Ruff, mypy, migration consistency, frontend lint/typecheck/build, Rust formatting/clippy and all three production image builds passed. Local API/session/CSRF checks and service health checks passed. No connected browser was available for a visual layout review.
