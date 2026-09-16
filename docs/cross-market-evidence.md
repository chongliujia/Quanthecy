# Macro and rates research

## Initial coverage and retention

The first research topic is macroeconomics and interest rates. Exchange observations
continue to come through the Rust collector. Reviewed pairs are explicitly selected;
this is not an exhaustive matching service. A similar title is not proof of equivalent
settlement, and a price difference is not an arbitrage recommendation.

The initial news worker reads only these public Federal Reserve RSS feeds:

| Source | Feed | Coverage |
| --- | --- | --- |
| Monetary policy releases | https://www.federalreserve.gov/feeds/press_monetary.xml | FOMC decisions, minutes and other monetary releases |
| Speeches | https://www.federalreserve.gov/feeds/speeches.xml | Federal Reserve speeches; topic relevance varies |

These feeds are listed in the [Federal Reserve RSS directory](https://www.federalreserve.gov/feeds/feeds.htm).
Poll each at most every 15 minutes, with conditional HTTP requests, bounded responses
(2 MiB) and at most 50 entries per response. Store feed-provided titles, excerpts,
publication dates, links, content hashes and immutable revisions in PostgreSQL.
No article pages or full-text archives are downloaded. There is no automatic deletion
policy yet; these low-volume metadata records remain until an operator explicitly
adopts a retention policy. This does not provide historical news coverage before
collection starts. The feeds may omit older entries, edits or deletions between polls.
Failed requests retain existing evidence and are visible in source status.

News collection is independent of market analytics. `NEWS_FEEDS_ENABLED=false` pauses
polling. `NEWS_PROXY_URL` optionally configures outbound requests. Only the source
registry's HTTPS feed URLs are fetched; redirects are refused. Articles remain links
to the publisher. The Linux loopback-proxy override also exposes PostgreSQL on
127.0.0.1:15432 for the news worker, alongside the existing local collector setup.

## Time and interpretation

Publication time is the publisher's claim. First observed time is when Quanthecy
successfully parsed an item. Each changed version has its own observed time; an older
published article fetched today was not available to this system yesterday.
Historical queries select only revisions and market associations known by the chosen
cutoff. A later correction never overwrites an earlier version. Feed entries with no
valid publication time carry an explicit unknown date.

Automatic associations use a deliberately broad, versioned topic rule: markets with
Federal Reserve / FOMC wording can be associated with these Fed feeds. They are marked
`TOPIC_ONLY`, with no causal claim. Operators can append a reviewed association or a
rejection in Django Admin. A review made today does not appear in yesterday's timeline.

## Comparison reviews

Pairs and their reviews are shared public research metadata. Customer workspaces do
not grant permission to curate these records; Django operator permissions do.
Reviews append revisions, freeze both rule snapshots and outcome IDs, and record
relation, alignment, reviewer, rationale, confidence and material differences.
Confidence expresses the reviewer's judgment about the match, not a calibrated
probability of equivalence. Revised exchange rules require a new review.

Comparison charts use backward-only alignment, at most 180-second-old samples and
at most 90 seconds between observations. Quote basis must match and outcomes must
match the reviewed selection. Invalid books, missing prices, closed markets, gaps,
stale samples and changed rules suppress the difference. `COMPLEMENT` alignment
transforms the right probability to `1 - p` and its bid/ask to `1 - ask / 1 - bid`.
Related contracts can show a contextual difference with the review's qualifications;
incompatible contracts cannot. Exchange quote times are unavailable for the initial
REST adapters, so alignment uses observation times and states this limitation.

Each chart point uses only observations received and recorded by that point, and
the review available then. This prevents a later review from being applied silently
to earlier prices. Requests are bounded to 24 hours, 10,000 observations per side
and 289 five-minute chart points. Truncated input is rejected rather than presented
as complete. The current comparison includes the exact two observation IDs for audit.
Collector `recorded_at` is the durable local journal time, not an assertion about when
the data became queryable in ClickHouse; storage outages can delay availability.

The first September 2026 FOMC candidates share an event, but their rounding,
cancellation fallback and closing-time metadata differ. They must be reviewed as
`RELATED`, with these differences retained. Reviewed manifests are imported with
`manage.py import_comparisons <file>` only after the collector has ingested the
selected markets. The import checks rule hashes and appends reviews at import time;
it cannot backdate review availability.

## Initial pair setup

The checked-in manifest is `configs/research/fed-september-2026.json`. It contains
two source-text reviews by Codex, explicitly labeled as not independently reviewed
by a human. Both pairs are `RELATED`: no change and a 25 bp hike at the September
2026 FOMC meeting. The source rule snapshots came from real Rust-collected data:

- Polymarket Gamma IDs `2252244` and `2252245`.
- Kalshi tickers `KXFEDDECISION-26SEP-H0` and `KXFEDDECISION-26SEP-H25`.

Add those IDs to `POLYMARKET_MARKET_IDS` and `KALSHI_MARKET_TICKERS` in `.env`, keeping
any existing explicit selections. Nonempty selectors replace the discovery universe;
include all markets you want to continue collecting, at most 50 per exchange.
Restart the collector and wait until all four markets appear in Market explorer:

```bash
docker compose up -d market-data
docker compose cp configs/research/fed-september-2026.json backend:/tmp/fed-pairs.json
docker compose exec backend python apps/backend/manage.py import_comparisons /tmp/fed-pairs.json
```

The importer refuses changed rule hashes and is idempotent for an unchanged review.
After expiry, select new meeting contracts and create new reviews rather than reusing
these dated pairs. Operators can add subsequent review revisions in Django Admin.

## API and frontend

All endpoints use the existing authenticated Django session. Shared research reads
do not require a customer to be a Django staff user. Curation uses operator permissions.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/research/overview` | Coverage counts and feed health |
| `GET /api/v1/comparisons` | Latest available review per pair |
| `GET /api/v1/comparisons/{id}` | Current alignment, five-minute history and reviews |
| `GET /api/v1/evidence` | Filtered/paginated official feed entries |
| `GET /api/v1/evidence/{id}` | Evidence revisions and latest known associations |
| `GET /api/v1/markets/{id}/timeline` | Source-linked topic evidence |
| `GET /api/v1/signals` | Latest 100 deterministic signals in the past seven days |

Comparisons, evidence and timelines accept an optional timezone-aware `cutoff` no
later than now. Comparison detail accepts `hours=1..24`; a review must already exist
at the cutoff. Evidence accepts `source`, `search`, `offset` and `limit=1..100`.
Signals accept platform and signal-type filters; the signal feed is a current view,
not a historical signal-availability archive. Overview source health is also current.

The React navigation links overview, market explorer, signals, comparisons, news
and workspace members. Hash routes preserve detail URLs and research cutoffs through
reload and browser back. Times are displayed in the browser's local timezone.
Frozen comparison rules, current input IDs, known gaps, source failures, empty history
and unreviewed evidence links remain inspectable. Market links from historical
evidence are explicitly labeled as opening the latest market view.

Evidence detail returns at most 100 revisions and 100 associations; market timelines
return at most 100 associations (with truncation indicated), displaying ten at a time.
The automatic topic-association pass considers at most 100 Fed-titled markets and
the 100 most recently first-observed selected feed entries. This deliberately bounded
MVP does not claim comprehensive news coverage or causal attribution.

## Verification record — 16 September 2026 (Asia/Shanghai)

- 98 Python tests passed using isolated PostgreSQL and ClickHouse. Coverage includes
  backward alignment, stale/missing/skewed quotes, changed rules, complementary
  outcomes, late-recorded observations, immutable evidence revisions, return to
  previous content, historical association rejection, source failures, conditional
  polling, XML entity rejection, authenticated APIs and operator-only curation.
- 16 React tests passed; ESLint, TypeScript/Vite production build, Ruff formatting
  and lint, mypy, Django system checks, migration consistency and shared-contract
  consistency passed. Both updated production images built. Development and
  production Compose configurations validated; deployment remains local.
- Eight local services were healthy. The existing 20-market universe was preserved
  and four Fed contracts added, giving 24 collected markets. Two `RELATED` reviews
  were imported. Both official feeds succeeded, yielding 30 entries and 120 topic
  associations at verification time. These are observed counts, not fixed targets.
- A real headless Chrome run against the local Nginx/Django deployment verified
  account registration, session login/logout, comparison history, evidence records,
  historical cutoff exclusion, detail reload, browser back, and the signal feed.
  Overview, comparison, market and evidence pages were checked at 390-pixel mobile
  width with no document overflow; desktop and mobile screenshots were inspected.
  No JavaScript errors occurred in the final workflow. Disposable smoke users and
  their workspaces were removed; existing application accounts were preserved.

The browser pass also exposed a sparse-history chart issue: a single qualified
sample now renders a visible point with an explicit history-availability notice.
The normal test suite uses fixtures and mocked feed requests; it makes no paid
model calls. No Agent execution or automatic trading was introduced in this milestone.
