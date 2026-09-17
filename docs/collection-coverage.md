# Research topics and managed collection

Operators curate a bounded set of exact exchange market IDs in Django Admin. The public market explorer filters this set by research topic; it does not discover or query exchanges from the browser.

## Operator workflow

1. Open `/admin/platform/coverage/` to inspect the desired revision, collector acknowledgement, and coverage by topic.
2. Use **Research topics** to maintain English/Chinese names and descriptions. Turning off public visibility hides the topic selector; it does not make public exchange observations private or stop collection.
3. Use **Collection targets** to add an exact numeric Polymarket market ID or uppercase Kalshi ticker, record the selection rationale, and enable/pause it. Every save requires a reason and creates an audit event tied to the operator UUID.
4. Confirm that the collector has applied the new revision. Then check actual observations and quality separately. Applied configuration is not proof that exchange requests succeeded.

Disabling a target or topic retains all market metadata, raw payloads, and history. A market included in multiple enabled topics is collected once; disabling one membership does not pause the other. Deletion is deliberately unavailable for these configuration records.

The initial bounds are 50 topics, 1,000 saved memberships, and 50 priority / 250 total enabled unique markets per exchange. Concurrent admin edits and plan publication share a PostgreSQL row lock, so their effective union is validated atomically. Long or failing exchange requests can still exceed the sampling budget; freshness and continuity gates remain authoritative.

## Activation

New installations continue using their existing collector configuration until managed collection is explicitly initialized. After Django migrations, run the bounded curated importer with an authorized staff operator:

```sh
docker compose run --no-deps --rm -T \
  -v "$PWD/configs:/app/configs:ro" backend \
  python apps/backend/manage.py import_collection_topic \
  /app/configs/research/fed-october-2026-collection.json \
  --actor operator@example.com
```

Before first activation, verify that the collector's `/status` universe has been reconciled into PostgreSQL. The importer preserves all existing market IDs under an operator-only `existing-coverage` topic; it refuses an oversized baseline rather than dropping markets. It never overwrites existing operator edits on a repeated import. A failed import rolls back all configuration changes. The checked-in October 2026 example contains five Fed decision buckets on each exchange, verified from the public APIs on September 16, 2026. Recheck contracts before reusing a dated manifest.

`setup_operator_roles` includes view access for data viewers and add/change access for data administrators. As before, it defines groups without assigning users or granting staff status.

## Delivery and recovery

- PostgreSQL owns `ResearchTopic`, `CollectionTarget`, and the singleton `CollectionPlan` revision.
- The analytics worker republishes the complete desired selection to Redis `collector:selection:v1` every worker iteration (normally 10 seconds), with a 300-second TTL. Publication does not depend on ClickHouse being available.
- Rust reads the selection while idle (every five seconds), at cycle boundaries before replaying pending batches, and between market requests. It validates schema, platforms, revision, exact ID syntax, deduplication, and bounds before saving it into the locked collector journal.
- Missing/invalid Redis data or a Redis outage retains the last valid configuration, including across collector restarts. Lower revisions and conflicting content at the same revision are rejected. Redis is not configuration truth.
- An enabled managed plan with empty platform lists intentionally pauses those platforms; it must not fall back to automatic discovery. Startup environment selection only applies in legacy mode.
- The acknowledgement key `collector:selection-status:v1` expires after 300 seconds; the console trusts an acknowledgement only for 180 seconds and only when its selection mode and revision equal the desired configuration. Runtime controls require schema version 2 or 3; directory controls require version 3. The current deployment assumes one collector with one durable spool.
- Restoring PostgreSQL to an older revision requires reconciling it with the retained journal before resuming changes. Do not clear the spool, because it also contains durable pending observations.

## Coverage semantics

`GET /api/v1/research/topics` and `GET /api/v1/markets?topic=<slug>` require normal application authentication. Only enabled, public topics are offered. An unknown, disabled, or hidden topic slug returns 404. The general market list continues to expose previously collected public exchange markets.

Counts are bounded to the saved topic memberships and evaluated from persisted observations, not expensive historical scans:

- **Configured**: enabled memberships in an enabled topic, including IDs not yet observed.
- **Observed**: a persisted market record exists; this alone says nothing about freshness.
- **Fresh**: an open market received within the past 180 seconds, excluding future timestamps.
- **Price/volume available**: independently pass the current data-quality policy and 15-minute window checks.
- **Missing**: configured target has no first observation.
- **Needs attention**: missing, closed, delayed, or quality-blocked targets. A fresh target that only needs history is shown as warming, not a collection outage.

New targets have no invented historical backfill. The quality policy requires at least 15 minutes of continuous valid data; interruptions can extend that time. A shared topic does not assert equivalent settlement rules, establish causation for news associations, or imply an arbitrage opportunity. Existing news linking labels Fed-topic associations as unreviewed `TOPIC_ONLY`. Contract expiry replacement and semantic cross-market review remain explicit operator/research work.

## Verification

Coverage tests exercise permissions and bilingual views, private-topic filtering, missing targets, deduplicated membership, activation limits, audited pause operations, invalid-edit rollback, idempotent imports preserving old coverage, and stale/mismatched acknowledgements. Rust tests cover revision conflicts, input bounds, explicit empty plans, durable restart recovery, and compatibility with old journals. The React test checks topic filtering and visible coverage gaps.

## Processing diagnostics and service recovery

The header and collection-health console now distinguish acknowledged pauses,
pending configuration, missing collector heartbeats, request failures and delayed
observations. They also report the analytics worker heartbeat used by in-app alerts.
Use [collection controls](collection-controls.md) to pause/resume each exchange and edit polling intervals without stopping containers. A manually stopped container still needs deployment recovery. See the
[watchlist operations guide](watchlists-alerts.md#collection-and-processing-state)
for recovery commands and the difference between liveness and data eligibility.

## Directory expansion

Use [market discovery and collection tiers](market-directory.md) to browse exchange catalogs, batch-select targets and lower polling frequency for standard or settled markets. Directory metadata is separate from observed price history.
