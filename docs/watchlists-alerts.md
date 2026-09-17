# Watchlists and in-app alerts

Watchlists connect the market scanner, research terminal and an organization-scoped
alert inbox. They follow already-collected markets; adding a contract does not
change the operator's collection plan or fetch an exchange from the browser.

## Use the workspace

1. Open **Watchlists & alerts**, select a workspace, and create a list. In a market
   terminal, choose **Watch market** to add the contract to an existing or new list.
2. Use the scanner or terminal sidebar's **Watchlist** filter to focus on that list.
   Reorder or remove its markets from the watchlist page. Archived lists disappear
   from active views and their rules are paused; existing alert history remains.
3. Add a rule: **midpoint change** in either direction, an increase, a decrease, or
   **spread widening**. Set a 5-, 15- or 60-minute window, threshold in percentage
   points, and a cooldown of 1–1,440 minutes. For example, a move from 40% to 45% is
   +5 pp. A spread moving from 1 pp to 3 pp widens by 2 pp.
4. Inspect notifications in **Alert inbox** or the terminal's **Alerts** tab. Trigger
   details retain the rule version, calculation version, observed window, quote
   values, source timestamps, rules versions and observation IDs. The inbox remains current during historical chart replay and labels this explicitly.
   The historical chart link uses the last input's availability time, including recording delay.

Lists and rules are shared by the workspace. Read/unread markers are personal.
OWNER, ADMIN and MEMBER can maintain lists/rules; VIEWER can read them and mark
only their own notifications. Django staff status does not grant workspace access.
Platform admins have read-only model views; mutation goes through workspace services.

Bounds: 20 active lists per workspace, 100 markets per list, and 10 rules per list
(including paused rules). Edit an existing rule when a list reaches its rule limit.
List names are unique ignoring case among active lists in the same workspace.

## Evaluation and delivery semantics

The existing Python market analytics worker evaluates new durable observations.
No LLM requests, trades, email, browser push or other external delivery are initiated.

- Windows use two-sided YES bid/ask midpoints. Spread means ask minus bid, not an
  executable return. The current research slice covers selected binary markets.
- The baseline is the latest observation at or before the window start, within
  150 seconds. At least 4 / 10 / 40 samples are required for 5 / 15 / 60 minutes.
  Consecutive samples must be strictly ordered and no more than 150 seconds apart.
- Both the latest observation and its price must be no older than 180 seconds when
  evaluated. Future inputs, missing/crossed quotes, non-open markets, conflicting
  duplicates, incompatible outcomes/rules/sources and excluded quality flags
  prevent a trigger. Volume eligibility is independent of these price/spread rules.
- Each historical query is bounded to 1,000 inputs; excess history blocks evaluation
  instead of silently using a truncated window. Inputs are limited by the current
  observation's recording time, so later-known data cannot enter its calculation.
- A first eligible matching sample records an alert. Further matching samples stay
  latched. Only a **valid nonmatching sample** re-arms the rule. Invalid data never
  re-arms it. A re-armed rule still respects its per-market cooldown.
- Editing, pausing or resuming a rule advances its revision. New rules, changed
  rules and newly added markets apply to observations received after the change;
  they do not backfill old notifications. Historical inputs before the change may
  form the baseline for a new observation. Prior cooldown survives rule revisions.
- The cursor and event are committed in the same PostgreSQL transaction as the
  ingestion checkpoint. A failed batch rolls them back together. Persistent cursors
  and a unique event key suppress duplicates after a worker restart. Quotes with
  non-advancing receipt times are not evaluated again for the same rule/market.
- Old catch-up observations fail the freshness gate. Worker downtime can therefore
  leave gaps in alerts; the inbox is not a complete historical crossing log.

An alert says the condition was **observed at a sample**. It does not identify the
exact time a price crossed the threshold between samples. The inbox polls every
30 seconds; end-to-end delay also includes exchange collection and worker processing.

The frozen snapshot retains compact normalized quote inputs, not full raw exchange
payloads. It survives rule changes and raw-data cleanup. Historical chart availability
still depends on retained ClickHouse history; the snapshot is not a replacement for
that history or the full settlement text.

## Collection and processing state

The header's collection diagnostics distinguish an acknowledged empty plan
(`paused`), an unacknowledged pause, a pending configuration, a source request failure,
missing recent collector telemetry, delayed saved observations and unavailable
diagnostics. An acknowledgment alone is not proof of fresh prices.

The worker publishes `worker:market-analytics:heartbeat:v1` after a successful
reconciliation cycle, with a 90-second TTL. This heartbeat shows processing liveness,
not that every market has eligible data. Per-rule states and per-market freshness
remain authoritative. Redis loss does not remove durable alert history.

Django Admin configures targets and evidence sources; it **does not start stopped
containers**. After applying migrations, a deployment operator can restore the
services required for new market alerts:

```bash
docker compose up -d market-data worker
```

Use the same Compose override files as the running installation (development:
`-f compose.yaml -f compose.override.yaml -f compose.dev.yaml`). News collection uses
`news-worker` separately. Agent processing is independent and is not needed for alerts.
Confirm both worker heartbeat and advancing valid market observations after recovery.

## API and storage

All routes use the authenticated Django session and CSRF for writes. Routes under
`/api/v1/organizations/{organization_id}` include:

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/watchlists` | List / create |
| GET / PATCH / DELETE | `/watchlists/{id}` | Inspect / rename / archive |
| POST | `/watchlists/{id}/items` | Add a market idempotently |
| DELETE | `/watchlists/{id}/items/{market_id}` | Remove a market |
| PUT | `/watchlists/{id}/order` | Reorder the complete list of market IDs |
| GET / POST | `/watchlists/{id}/rules` | List / create rules |
| PUT | `/watchlists/{id}/rules/{rule_id}` | Update settings or enabled state |
| GET | `/alerts` | Inbox with bounded pagination, unread and market filters |
| GET | `/alerts/{event_id}` | Frozen trigger detail |
| PATCH | `/alerts/{event_id}/read` | Change the caller's read receipt |

The scanner accepts both `watchlist_id` and `organization_id`; it enforces membership
and list ownership before filtering. All new transactional tables use Django
migrations. The numerical window evaluator lives in `quanthecy_analytics.alert_metrics`;
ClickHouse is queried through its dedicated repository. No new public backend or
independent queue is introduced.

Tests cover tenant and role boundaries, CSRF, invalid rules, quote eligibility,
window units, restart deduplication, re-arm/cooldown, revision retention, checkpoint
rollback, personal read state, translated direction values and timestamp replay links.
