# Market history and deterministic signals

Milestone 2 implements bounded public REST collection, market research APIs and
the market explorer. Cross-platform matching, news and Agent execution remain
the next milestones.

## Start and inspect

Run the Compose startup in [README](../README.md), register an account, then choose
**Market explorer** in the workspace navigation. There is no default account or
password. Django operators are created separately with `createsuperuser`.

The default collector selects up to **10 binary markets per platform**, from at
most two discovery pages of 100 markets each. It orders this bounded candidate
set by reported cumulative volume. This is not an exchange-wide ranking or a
representative statistical sample. Markets are pinned in the collector volume
after discovery; restarts preserve the selection and continue checking lifecycle
state. Closed markets stay in history. The collector does not automatically replace
them or expand its universe. Set comma-separated `POLYMARKET_MARKET_IDS` and
`KALSHI_MARKET_TICKERS` to select a deliberate research universe (maximum 50 each).
Changing these variables takes effect when the collector is recreated and does
not erase previously collected history.

Snapshots run on a target **60-second** interval, with a 250 ms pause between
market requests. Timeouts and retries can extend the cycle. The configurable
interval is clamped to 15–3600 seconds; the initial analytics definition assumes
gaps no greater than 150 seconds, so slower sampling can correctly yield no
15-minute metrics. Discovery and requests are public and require no exchange
credentials. Only the YES outcome of supported binary contracts is collected.

History starts at actual collection. This release has no backfill, WebSocket tick
capture, trades, order-book depth, or candle rollups. REST sampling cannot recover
movements between polls. The detail view shows collection start, latest observation,
staleness, quality flags and available history. Market-wide volume is stored once
per YES snapshot, not duplicated across outcomes. Historical retention has no TTL;
disk capacity and backups must be managed by the operator.

## Optional local proxy

On Linux, a proxy listening only on host `127.0.0.1` cannot be reached from a
normal container bridge. `compose.proxy.yaml` is an optional local override:

```bash
cp compose.proxy.yaml compose.override.yaml
# Set COLLECTOR_EGRESS_PROXY in .env if the proxy uses a different address.
docker compose up -d --wait
```

The ignored `compose.override.yaml` is automatically included by ordinary Compose
commands. This local configuration gives only the collector host networking,
binds its internal endpoint to `127.0.0.1:8080`, and exposes ClickHouse/Redis only
on `127.0.0.1:18124` and `127.0.0.1:16380` so that the collector can reach them.
It uses the existing host proxy (default port 7897), with local storage excluded
from proxying. Use this override only for local development; production commands
explicitly select `compose.yaml` and `compose.prod.yaml`. Remove the local override
and recreate services to return to the default bridge-only setup.

`make dev` includes the local override when present. With explicit Compose file
arguments, include `-f compose.proxy.yaml` as well when the proxy is required.

## Source semantics

Verified against official documentation and public responses on 2026-09-15:

- [Polymarket Gamma markets](https://docs.polymarket.com/api-reference/markets/list-markets):
  discovery and selected-market reads use `/markets`; `id` filtering retains event
  relationships that the single-market response may omit. Only `Yes, No` ordered
  binary outcomes are accepted; the YES CLOB token supplies the outcome identifier.
  Probability is the midpoint of `bestBid` and `bestAsk`. `volume` is the source's
  cumulative dollar-denominated volume, labelled `USD` and with its source basis.
- [Kalshi public market data](https://docs.kalshi.com/getting_started/quick_start_market_data)
  and [market schema](https://docs.kalshi.com/api-reference/market/get-markets):
  the production endpoint is `external-api.kalshi.com/trade-api/v2`. Only binary
  contracts with a one-dollar notional are accepted. Prices use `*_dollars` and
  quantities use `*_fp`; bids/asks require positive quoted sizes. Cumulative
  `volume_fp` retains the `CONTRACTS` unit. Deprecated `liquidity_dollars`, which the
  source documents as always zero, is not interpreted as observed liquidity.
- Both adapters leave liquidity null. Zero/one endpoint quotes can be sentinels;
  only interior, non-crossed, two-sided quotes in open markets yield a midpoint.
  A null probability is never replaced by last trade price or zero.
- These REST metadata responses do not establish the exchange time of each quote.
  `event_at` is null and `SOURCE_TIME_MISSING` is explicit. Probability/volume
  `as_of` use local receipt time. Metadata `updated_time`/`updatedAt` is not used as
  a trade timestamp. `recorded_at` records journal staging time. Timestamps use UTC.
  This supports research about observed snapshots, not claims about exact trade time.
- Rule versions hash question text, rules, close time, resolution source and
  outcome identity. Unknown rules are retained with `PARTIAL` and excluded from
  signal generation. Raw source objects are retained with canonical JSON SHA-256
  hashes; the hash covers parsed, sorted-key JSON, not original HTTP bytes.

The small `market-rest.json` fixtures retain only public fields needed by adapters.
The older `observation.json` fixtures and `research-window.json` are explicitly
synthetic. They must not be presented as actual market evidence.

## Data ownership and recovery

```text
Rust REST adapters → locked, fsynced journal in collector_data
                   → ClickHouse observations → committed batch marker
                   → Redis latest state (TTL = 3 × target interval)

Python worker → committed batches → deterministic analytics → ClickHouse signals
                                 → Django ORM metadata + PostgreSQL checkpoint
React → Django Ninja → application services → repositories
```

The shared `identity/v1` protocol derives UUIDv5 IDs using `NAMESPACE_URL` and
`https://quanthecy.org/identity/v1/{platform}/{kind}/{exchange_id}`. Django validates
the mapping and owns Event/Market/Outcome rows and all PostgreSQL writes. Publishing
this deterministic mapping lets Rust identify observations without synchronous
backend RPC or a second implementation of application-domain logic. Future market
matching creates relationships between platform IDs; it does not merge their IDs.

The collector has one locked journal per instance. A pending batch preserves its
collector ID, increasing batch number, observation IDs, raw inputs and timestamps
through retries. ClickHouse observations are inserted before the commit marker.
Both writes are synchronous; a failed or lost acknowledgement is safe to replay.
`ReplacingMergeTree` plus `FINAL` reads deduplicate replayed logical records.
Repeated observations at different collection times remain distinct samples.

The worker advances its PostgreSQL checkpoint only after a complete, contiguous
committed batch is reconciled transactionally. Signal IDs derive from calculation
version, ending observation and signal type, making a retry after a PostgreSQL
rollback idempotent. Late observations cannot overwrite newer PostgreSQL metadata
or Redis state. Redis loss does not block durable ingestion or analytical work.
The detail API falls back to the persisted metadata snapshot.

When ClickHouse fails, the pending batch is retained and collection pauses until
it is delivered. Interruption cannot restore source activity that was never
observed. The next observation is marked `GAP` if its receipt time exceeds twice
the configured interval plus 30 seconds. Source failures are logged by platform
and market; HTTP 429/5xx and network errors have bounded exponential retries, with
numeric Retry-After support. Shutdown cancels in-flight requests and retains staged
batches. Responses still in memory before journal staging are not guaranteed.

Preserve and back up **collector_data together with ClickHouse and PostgreSQL**.
Do not manually edit batch numbers or remove a pending journal. A restored
checkpoint ahead of restored analytical data requires deliberate reconciliation;
the worker will not silently skip missing batches. Migration deployment is a
single-operator workflow, not a concurrently executed background task.

Rust `/health` reports process liveness; `/status` and `/ready` describe collection
cycles and failures. Container liveness alone does not prove fresh source data.
Inspect logs using `docker compose logs -f market-data worker`.

## Signal definition: rest-window-v3

Version 3 retains the research thresholds below and shares a numerical tolerance
between volume-reset detection and activity rates; see the
[research data quality policy](data-quality.md). Existing v1 and v2 signals retain
their original IDs and behavior through `signals.replay(saved_version, inputs)`.

Analytics run in the Python worker, never in an HTTP request or LLM. The initial
definition requires an observed 15-minute window, at least ten samples, no interval
above 150 seconds, compatible market/outcome/rules, and open lifecycle status.
Missing history, invalid quotes and gaps produce null metrics and explicit reasons.

| Signal | Calculation and threshold |
| --- | --- |
| PROBABILITY_SPIKE / PROBABILITY_DROP | Last minus initial YES midpoint; absolute change ≥ 0.05 (5 percentage points) |
| SPREAD_WIDENING | Change in YES ask minus bid; increase ≥ 0.03 (3 percentage points) |
| VOLUME_SPIKE | Last observed cumulative-volume increment per second versus preceding interval rates; population z-score ≥ 3 and rate ≥ 2 × baseline mean |

A cumulative-volume reset suppresses volume calculations. A constant baseline has
an undefined z-score and remains null. Units are never pooled across exchanges.
Signal score is threshold-relative magnitude capped at one; it is not an event
probability or a calibrated prediction. Signals are emitted per qualifying sample;
Agent-trigger cooldowns and publication deduplication belong to milestone 4.

Signals preserve version, parameters, window, metrics and exact observation IDs.
Their full normalized inputs can be exported. The notebook
[reproduce_signal.ipynb](../notebooks/reproduce_signal.ipynb) reads either format and
recomputes the same IDs and metrics. Its default fixture deliberately triggers all
three signal families and requires no network, model, or credentials. Execute it
with the Python 3.12 environment created by `uv sync --frozen`; Jupyter is an optional
viewer, not a backend runtime dependency.

## API and query limits

All routes below require the existing Django session. Exchange observations are
shared public research data, so they have no Organization owner. Private watchlists
and future Agent runs must remain organization-scoped.

| GET route under `/api/v1` | Behavior |
| --- | --- |
| `/markets` | Search, platform filter, offset/limit pagination; `recent`, `movement`, `volume_anomaly` sorting |
| `/markets/{id}` | Persisted metadata, fresh-cache fallback, quality, coverage and calculated metrics |
| `/markets/{id}/history` | Normalized observations; timezone-aware `start`, `end`, `limit` |
| `/markets/{id}/signals` | Latest 50 explainable signals for that market |
| `/markets/{id}/export?format=csv` | Full observations in CSV; `parquet` also supported |
| `/signals/{id}/inputs?format=csv` | Exact evidence for one signal; rejects incomplete evidence |

Movement/anomaly rankings exclude stale, closed and uncomputable markets. A
snapshot older than 180 seconds is stale. History defaults to the previous day,
allows at most seven days, and returns up to 10,000 observations with explicit
`truncated` status. Exports reject truncation; reduce the time window for complete
results. These bounded snapshot queries are the initial research interface.
Larger histories and tick-level dashboards will require rollups and background
exports before increasing coverage.

## Verification

Normal tests use fixtures and mocked exchanges. To opt in to the actual ClickHouse
repository test, set `QUANTHECY_TEST_CLICKHOUSE_URL` to an isolated development
ClickHouse with the example development credentials. The test creates a uniquely
named temporary database and drops only that database on completion. PostgreSQL
tests use pytest-django's separate test database.

Verified locally on 2026-09-15:

- **73 Python tests** passed against PostgreSQL, including the opt-in real
  ClickHouse integration test. Replay deduplication, complete/contiguous batch
  checks, atomic checkpoint behavior, metadata ordering, unavailable storage,
  authentication, bounded queries and export reproduction were exercised.
- **9 Rust tests** passed, including shared contract fixtures, real-source parser
  fixtures, malformed/missing numbers, unsupported contracts, crossed quotes,
  stable observations, gap/out-of-order flags and locked journal recovery.
  Formatting, Clippy and the Docker checks target passed.
- **10 frontend tests** passed, including unavailable/empty markets, filters,
  stale details and null probabilities. Lint, TypeScript/build and the Docker
  checks target passed. The chart is loaded separately from the market list.
- Ruff lint/format, mypy, contract drift, Django migration consistency and
  idempotent ClickHouse migration checks passed. Notebook code cells executed in
  the locked Python environment and both formats reproduced identical signals.
- Production images built. The local Compose upgrade retained existing storage
  and all seven long-running services returned healthy.
- Live public source collection saved Polymarket and Kalshi data. In an isolated
  interruption test, ClickHouse was stopped, a two-observation batch was confirmed
  on disk, and the collector was terminated. After both restarted, the same batch
  and observation IDs were delivered. Historical gaps remained explicit and Redis
  resumed current-state writes with its configured TTL.
- The default local universe contains **10 markets per platform**. Real HTTP
  requests through Nginx exercised session login, platform filters, detail,
  history, CSV and Parquet. Both exchanges returned fresh cached data, and each
  export pair contained identical normalized inputs. The temporary smoke-test
  identity and isolated test containers were removed.

This machine requires its existing loopback proxy for outbound market requests;
the optional Linux local override is enabled in ignored `compose.override.yaml`.
Initial images were built using cached public upstream images and, where needed,
the existing host proxy for package downloads. No real-browser connection was
available, so visual inspection was not performed; component and HTTP checks do
not establish visual correctness. No public deployment, news integration, LLM
execution, or paid model trial was performed. Live 15-minute analytics warm up
from collection start; the reproduction example uses explicitly synthetic data.
