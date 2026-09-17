# Research terminal and workspace models

The Agent inspector now includes [multi-expert intelligence](intelligence-team.md):
five versioned skills, scoped evidence, risk review, conditional forecasts and
per-stage audit records. The collaboration mode reserves five requests; quick
single-Agent research reserves one. Both remain explicitly initiated by a user.

The market detail page is a chart-centered research workspace inspired by financial
terminals. It uses the existing ECharts dependency and Quanthecy's Django APIs.
TradingView libraries, trademarks, market feeds, and proprietary UI assets are not
embedded.

## Using the terminal

Open **Market explorer**, then select a contract. On desktop, the market table
scrolls below its fixed filters and above pagination. Above 1100px, the desktop terminal
fits the available window height. A compact quote strip sits above the main chart;
the right panel switches between **Markets** and **Research**. News, signals and
research content scroll within their own panels, keeping chart controls and activity
tabs visible. Exceptionally short windows, expanded context and enlarged text can
still scroll instead of clipping content. Smaller screens use a single column.

The searchable market list shows up to 40 results and is not a saved watchlist.
**Research & agent** and event selection open the inline research panel on desktop;
the expand button opens a wider drawer. Agent research opens in the wider drawer
so multi-expert reports stay readable. Below 1100px, use **Switch market** and the
research drawer. Escape closes a drawer and returns focus to the research trigger.

The navigation rail and side panel can collapse. Drag the vertical separator to
resize the side panel. Open a bottom activity tab, then drag its upper separator
to allocate space between the chart and activity. Separators also support arrow
keys, Home/End and double-click reset. Panel sizes and visibility persist locally
per user, without storing credentials; viewport limits keep the chart usable.

Use **中文 / English** in the top bar to change the interface language. The choice
persists across reloads and changing it does not clear form drafts. Market titles,
contract rules and source excerpts retain their original text; no translation
model is invoked. Date readouts use the selected locale and local timezone.

- Choose 1H, 6H, 1D, or 7D; scroll to zoom and drag to pan across all three panes.
- With enough height, the probability pane gets 60% of the canvas. Below 300px
  canvas height, the chart uses a probability-only view; volume and spread remain
  in the readout. Expand the chart to see their individual panes. Automatic
  probability scaling is on initially, with a 0–100% option. The fixed readout shows observation time,
  YES midpoint, bid/ask, sampled volume change and spread. Expand the chart to fill the
  viewport; zoom survives expansion and restoration.
- Diamonds group stored signals in five-minute buckets; a count retains every
  underlying signal for selection in the inspector. Signal rows remain individual
  records. News squares use separate display offsets and five-minute groups based
  on when revisions were first observed, when a nearby probability sample exists.
  A news group is a collection-time group, not evidence of simultaneous publication.
  The inspector and signal ledger emphasize the metric appropriate to each type:
  probability change, spread change, or volume-rate z-score.
- The Signals, News & evidence, Related markets, and Data tabs expose source inputs,
  evidence associations, reviewed comparisons, and recent observations/exports.
- **Time context** creates a shareable historical cutoff. Detail prices and rules
  come from historical observations, not today's metadata or Redis cache. History
  excludes observations recorded after the cutoff. The sidebar explicitly stays
  on current quotes. Evidence selected from a signal is restricted to what was
  available at that signal's timestamp.
- The Contract inspector preserves settlement wording and rule versions. The
  Agent inspector provides on-demand research and the last 20 workspace runs for
  this market.

Chart values are YES bid/ask midpoints, not independent probability forecasts.
Volume bars show changes between consecutive compatible REST samples, not
individual trade executions. Gaps, counter resets, changed volume bases, and mixed
units are not filled with invented volume. A change in a rolling-volume counter
is still a counter change, not an interval trade-volume estimate. Spread is in
percentage points. Reviewed cross-platform comparisons remain on the comparison page.

### Comparative chart views

The terminal's **Single contract / Event comparison / Heatmap** switch reuses the
main chart area. It does not append another dashboard below the chart. Contract
lists and heatmap tiles scroll inside their panels on desktop.

- **Quote band** is enabled initially on the single-contract chart. The shaded
  interval spans the sampled best bid and ask, with explicit gaps for missing,
  crossed, invalid or stale quotes. Auto scaling includes both boundaries. It is
  a REST quote range, not order-book depth or executable size.
- **Heatmap** shows the current workspace's selected watchlist or the collected
  market sample. Equal-size tiles encode qualified 15-minute changes in percentage
  points; the fixed color scale saturates at ±5 pp without capping the printed
  number. Unavailable/stale windows are gray and display a dash; a valid unchanged
  window displays `0.00 pp`. Quotes expire after 180 seconds even if refresh fails.
  Platform filtering and pagination (60 tiles per page) keep coverage explicit.
  Click a tile to open its contract. Heatmaps are disabled at historical cutoffs.
- **Event comparison** uses operator-recorded event links, restricted to those
  visible at the research cutoff. Select 1–6 contracts, a platform, a 1H/6H/1D
  window, and either historical lines or bars at the cutoff. Related contracts
  can overlap and have different settlement rules: values are independent and
  are never normalized into a 100% distribution. A link is not equivalence review.

`GET /api/v1/research/events/{slug}/chart` is an authenticated, typed Django Ninja
endpoint. It reads up to 3,000 recent observations per selected contract through
the analytical repository and reports truncation. At most 100 linked contracts
are selectable. Python aligns observations to a shared 60-second grid plus the
exact window endpoints. A quote must have been received **and recorded** by that
grid point, be at most 90 seconds old (including its price timestamp), pass the
price-quality checks, and match the linked rules and outcome. Invalid latest
quotes, contract changes and gaps remain blank; there is no nearest-future match,
interpolation, or fallback to an older valid quote. The response retains actual
observation times and IDs. Collection intervals longer than 90 seconds naturally
produce gaps rather than silently extending quote freshness.

The interface uses restrained quote/transition animations and respects reduced
motion preferences. The data table and signal/evidence controls provide accessible
alternatives to interacting with canvas markers.

## Collection status and delayed data

The authenticated `GET /api/v1/collection/status` Django API reports each platform's
latest persisted observation, age, fresh open-market count, and optional collector
diagnostics. The shared status strip refreshes every 30 seconds; expand a source
for details. Quotes older than 180 seconds are delayed. Source recency does not
promise every collected market is open or fresh.

Rust publishes the last attempt's allowlisted error category to Redis with a
five-minute TTL and a 500ms write deadline. Redis loss cannot block ingestion or
hide PostgreSQL-derived freshness; missing, expired, malformed or unrecognized
telemetry is not presented as a known cause. No raw exception, proxy URL or secret
is returned. The telemetry describes the latest source attempt, not a guarantee
that all earlier requests succeeded.

Stale market views show age and explain that quotes/changes belong to the saved
observation. **View last collected window** opens an explicit historical cutoff
including that observation's recording time. Empty fresh rankings identify
collection delays instead of describing all empty results as initial warm-up.

For local development requiring the existing loopback proxy, use `make dev` or
include `compose.override.yaml` when providing explicit Compose file arguments.
See [local proxy setup](market-research.md#optional-local-proxy). Do not omit the
local override when recreating collectors: their liveness health check alone does
not establish successful exchange access.

## Configuring a model in the web application

Models start disabled. In **Model settings**, the active workspace's OWNER can set:

- provider presets for OpenAI, DeepSeek, Qwen, Kimi, SiliconFlow, OpenRouter,
  Gemini compatibility mode, and native Anthropic Messages;
- API base URL and exact model ID;
- optional API key (required for OpenAI), replacement or removal;
- daily request limit and maximum output tokens;
- whether workspace members can request on-demand research.

Saving configuration does not contact the provider. **Send test request** explicitly
queues one small JSON generation, even while research is disabled, and may incur
the provider's charge. It contains no research context. Research requests are also
explicit button actions. No live or paid model was used to verify this feature.

Only owners may change/test connections. OWNER, ADMIN, and MEMBER may request
research when enabled; VIEWER may read reports. Every API query constrains the
organization. Django staff status grants no implicit access.

### One-time server setup

Local `make dev` and `make up` initialize a missing `AGENT_ENCRYPTION_KEY` in the
ignored `.env` file with owner-only permissions. Existing keys are preserved and
the generated value is never printed. For an already-running local installation,
run `make setup-local` and recreate backend and agent-worker to load it.

For production, the platform operator must set `AGENT_ENCRYPTION_KEY` to a Fernet key before API
keys can be saved. Generate it in a trusted local shell with:

```bash
docker compose run --rm --no-deps backend python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Store that output as `AGENT_ENCRYPTION_KEY` in your untracked `.env` or deployment
secret store, then recreate backend and agent-worker. Keep the key stable and back
it up separately from the database. Rotating or losing it requires re-entering
workspace provider keys; an automatic key-rotation workflow is not implemented.
Provider keys are encrypted using Fernet, never returned by the API, never stored
in browser storage, and not logged. Changing the endpoint requires replacing or
removing its saved credential so it cannot silently be forwarded elsewhere.

`AGENT_ALLOWED_ENDPOINTS` is an exact comma-separated allowlist of trusted API base
URLs. Leaving it empty enables the public endpoints in
`quanthecy/agents/catalog.py`; setting it explicitly replaces that catalog. Add
your trusted compatible gateway or local server to an explicit list before using
that address. The page displays an unapproved-address warning before saving. HTTP is supported only
for endpoints explicitly trusted in this operator-controlled list; use HTTPS for
remote providers. Do not allow domains controlled by untrusted tenants. Production
network egress restrictions should also constrain allowed destinations. Redirects
are refused. Local endpoints must be reachable from the worker container, not just
from the browser's machine.

The Chat Completions adapter calls `POST {base_url}/chat/completions` with JSON
object mode and no tools or streaming. OpenAI uses `max_completion_tokens`; the
compatible protocol uses `max_tokens`. Anthropic uses `POST {base_url}/messages`,
a separate system prompt and API version header. Text must pass the same JSON
schema and evidence checks. These are protocol adapters, not a claim that every
model or account was tested against a live provider.

Changing providers requires a replacement credential or explicit removal; the UI
does not silently delete the saved key. Cloud presets cannot be enabled without a
key. Known incompatible OpenAI endpoint / model combinations are rejected before
saving or queuing. Failed requests distinguish authentication, connectivity,
timeout, quota, rate limits, HTTP errors and output truncation using allowlisted
codes passed through the isolated worker. No provider error bodies are exposed.

The endpoint/model must support the configured parameters. The application
validates the returned report schema and evidence references independently.
[Chat Completions reference](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).

## Worker and report lifecycle

```text
Explicit request → organization admission + idempotency → PostgreSQL job
    → agent-worker → freeze context → one bounded model call
    → schema + reference validation → stored workspace report
```

`agent-worker` uses the same Python image as Django and is included in local,
development, and production Compose configurations. It never runs work inside
HTTP handlers. Jobs progress through PENDING, RUNNING, and SUCCEEDED/FAILED/CANCELLED.
The queue is durable in PostgreSQL; Redis loss does not erase it.

One pending/running job is allowed per organization. The daily UTC limit counts
all admitted requests, including tests, failures, and cancellations. There is one
provider attempt per job, a 60-second wall-time bound in an isolated subprocess,
a 128 KiB response bound, and a three-minute claim lease. Expired leases and jobs
queued for more than ten minutes fail visibly. Ambiguous calls are never retried
automatically; the user can submit a new request. Provider token usage is recorded
when returned, including a returned response discarded after cancellation.
Unavailable usage is not zero usage. These are request/token limits, not a
currency budget or billing reconciliation system.

Changing model settings cancels outstanding jobs. Lease fencing prevents a stale
worker from publishing after cancellation or expiry. Roles and configuration
revision are rechecked before a model call and before publication. Cancellation
cannot undo a provider request already submitted.

The context includes up to 20 minutes/1,000 observations, deterministic metrics and
signals, contract rules, up to eight associated news revisions and five reviewed
comparisons. It is bounded to 48,000 serialized characters before adding the output
schema. Full input observations are stored locally, while only the compact context
is sent to the configured provider. A historical cutoff applies to observation
recording time, evidence revision availability, associations, and comparison reviews.
Signals in Agent context are recalculated using the current versioned analytics
implementation from those frozen observations.

Reports contain a cited thesis, classified claims, counter-evidence, risk flags,
follow-up suggestions, and IGNORE/WATCH/INVESTIGATE research priority. Confidence
is explicitly labeled as the Agent's research-priority confidence, not an event
probability or calibrated accuracy. Referenced metric values remain available in
the frozen-reference inspector. Schema/citation validation does not establish that
a claim follows from evidence; live-model quality evaluation remains future work.

This vertical slice does not implement signal-triggered automation, daily digests,
watchlist schedules, automatic retries, or currency budget reservation. Those remain
in the broader [automatic research design](automated-research.md).

## Verification

Backend coverage includes actual PostgreSQL constraints, concurrent admission,
CSRF/role/tenant boundaries, credential encryption and redaction, endpoint changes,
late data, invalid citations, cancellation during provider calls, and lease expiry.
Model requests are mocked. ClickHouse integration verifies as-of filtering while
preserving complete collector replay.

Frontend coverage includes model save without test calls, secret-field clearing,
viewer access, signal/evidence cutoff linkage, and truthful chart data transforms.
Independent headless Chrome checks cover 1920px, 1440px and 390px layouts, real canvas
rendering, signal selection, chart expansion, disabled-model state, and model saving.
The original screenshots below use labeled synthetic QA fixtures.

The subsequent usability pass used an actual browser login and real locally
collected data. It verified event-group drill-down (all five selected signals),
zoom retention through modal expansion, pointer and keyboard resizing with reload
persistence, source diagnostics, and mobile drawer focus/closure without horizontal
overflow. Models remained disabled. Numerical tests cover flat/extreme probability
axes, missing values, and event grouping without losing input records.

Actual historical-view previews, labeled HISTORICAL in the app:
[1440px terminal](screenshots/terminal-review-desktop.png),
[expanded chart](screenshots/terminal-review-fullscreen.png), and
[mobile signal drawer](screenshots/terminal-review-mobile.png).
These are recorded market observations viewed at a cutoff, not live forecasts.

Synthetic QA previews: [desktop terminal](screenshots/research-terminal.png) and
[web model configuration](screenshots/model-settings.png).


### Bilingual redesign verification

The revised settings page and chart workspace were inspected in an isolated Chrome
session at 1440px, 1920px and 390px with real locally collected market history.
Language changes preserved a model draft; the secret field accepted a synthetic
key, saved it encrypted, cleared the input and did not return it after reload.
The synthetic key was removed afterward. No provider generation was requested by
these checks. User-initiated requests are separate from UI verification.

New screenshots: [Chinese model settings](screenshots/model-settings-zh.png),
[English model settings](screenshots/model-settings-en.png), and
[Chinese chart workspace](screenshots/terminal-zh.png).

The workspace uses fluid width instead of a fixed content cap. Settings allocate
two thirds of the available space to the connection form and one third to the
analysis and connection-test cards, stacking on smaller screens. Loaded overview,
market-list and settings pages were checked at 2560px, 1920px, 1440px and 390px:
content reaches the normal page padding without an unused right column or page
overflow. [2560px settings preview](screenshots/model-settings-wide.png).

Provider endpoint references: [DeepSeek](https://api-docs.deepseek.com/),
[Qwen](https://help.aliyun.com/en/model-studio/base-url),
[Kimi](https://platform.moonshot.ai/docs/api/chat),
[SiliconFlow](https://docs.siliconflow.cn/docs/userguide/quickstart),
[OpenRouter](https://openrouter.ai/docs/quickstart),
[Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai), and
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create).
