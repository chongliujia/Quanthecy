# Market directory and collection tiers

The market explorer has two views: **Collected markets** for historical prices and analytics, and **Market directory** for discovery metadata. Finding a market does not manufacture price history or make it eligible for Agent analysis.

## Operate coverage

Open **Market discovery** at `/admin/platform/directory/`:

1. Expand **Discovery & standard tier settings** and enable directory discovery. Exchange switches at `/admin/platform/controls/` also pause discovery for that source.
2. Set the pause between scans (300–86,400 seconds), page spacing (5–300 seconds), and page budget (1–1,000 pages per exchange). Defaults are 3,600 seconds, 10 seconds and 200 pages; pages contain at most 100 exchange records. A capped scan is explicitly partial coverage.
3. Search titles or exact IDs. Select an exchange to sort by reported 24-hour volume; USD and contract counts are not ranked against each other.
4. Select up to 50 recent, open entries, an enabled research topic and a collection tier. Supply an audit reason and save. This requires an initialized managed plan plus platform permissions to add/change collection targets and change the plan.
5. Use **Collection targets** to pause memberships or edit their tiers. For a market in several enabled topics, the fastest tier wins. Pausing one membership does not disable other memberships.

Limits: 50 research topics, 1,000 stored memberships, 50 priority markets and 250 total enabled unique markets per exchange. Standard targets use the configurable standard interval (default 300 seconds, range 60–3,600); priority targets use their source interval. The source interval is always a lower bound. Acknowledgement, actual freshness and analytical eligibility are separate checks.

Low-frequency samples may fail the existing short-window analytics and alert continuity gates. Those gates are not relaxed: missing indicators remain unavailable. Move markets needing short-window research into the priority tier and allow sufficient continuous history to accumulate.

## Discovery and durability

- Rust runs directory discovery in an independent task with its own locked `catalog/` spool under `COLLECTOR_STATE_DIR`. Quote polling does not wait for directory requests.
- Polymarket uses [`/markets/keyset`](https://docs.polymarket.com/api-reference/markets/list-markets-keyset-pagination) with `next_cursor` / `after_cursor` and `closed=false`. Kalshi uses [`/markets`](https://docs.kalshi.com/api-reference/market/get-markets) with `status=open`, `mve_filter=exclude` and the returned cursor. Both use 100 records per request and the existing bounded retry policy.
- Only contracts supported by the current normalizers enter the directory: Polymarket Yes/No markets and Kalshi binary one-dollar contracts. Skipped records are counted. No completeness claim includes unsupported contract types, settled historical catalogs or a capped/failed scan.
- Every accepted page and next cursor are saved together before delivery. A single ClickHouse `market_catalog_pages` record stores the page. Retries use the same collector/page identity. The Django worker validates and reconciles pages in order into PostgreSQL `CatalogMarket`, with a separate checkpoint. Redis only delivers settings and transient health.
- Directory entries retain first/last observed timestamps. Replayed older pages cannot replace newer metadata. A market disappearing from open listings is **not** evidence that it closed; its last known metadata stays visible with a stale indicator after 24 hours.
- Schema 3 carries discovery settings and per-market quote intervals. Schema 1/2 and existing spool files remain readable. Missing Redis data retains the last persisted configuration. Discovery starts disabled until an operator enables it.
- HTTP failures, malformed pages and non-advancing cursors retain the checkpoint and retry after 60 seconds. They do not silently skip pages. Inspect collector logs and fix source connectivity/cursor errors before assuming scan completion.

## Quote scheduling and lifecycle

Quotes are scheduled per market, with at most 50 attempted requests per source per cycle. Oldest attempts go first, including failed requests, so a failing subset cannot monopolize the batch. The minimum per-market interval survives restarts through stored observation times; failed-attempt pacing is transient. Slow responses and retries can make actual sampling slower than configured.

Selected markets observed as `CLOSED` are revisited at most hourly; `RESOLVED` markets are revisited at most daily. These checks can capture final results or reopenings. A later successful `OPEN` observation restores the configured tier. History, raw observations and topic membership are retained. Missing an open-directory scan never triggers this transition. Pausing the source or all memberships stops these rechecks too.

The directory does not automatically promote every discovered market, replace curated topics or run paid Agent requests. Operators choose the research universe through audited bulk selection. The public `GET /api/v1/market-directory` endpoint requires application authentication and provides bounded search, exchange filters and pagination; the browser never calls exchange APIs.

## Deployment

Apply `setup_storage` (Django and ClickHouse migrations), rebuild `market-data`, and restart the backend and worker. Keep the existing collector state volume. The first scan fills the directory progressively; new selected markets build history from their first quote observation.
