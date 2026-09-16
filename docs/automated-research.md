# Automated research

Status: target design for the complete automatic-analysis MVP. An on-demand
vertical slice is implemented: web model configuration, encrypted organization
credentials, durable research jobs, frozen context, validation, and reports.
The [single-market expert team](intelligence-team.md) adds five bounded specialist
stages, scoped working memory and conditional forecasts alongside quick research.
See [implemented behavior and limits](research-terminal.md). Signal triggers, daily
digests, schedules, automatic retries, and currency budgets below remain proposed.

## Responsibility boundaries

```text
Rust market ingestion → historical observations + live state
Selected source adapters → versioned news / announcement evidence
                                │
                                ▼
Python deterministic analytics → signals → candidate selection
                                │
                                ▼
Organization policy → durable job → evidence context → single Agent
                                │
                                ▼
Validation → stored report → organization research feed / daily digest
```

Rust continues to own exchange ingestion and realtime market processing. Python
owns analysis, evidence association, context construction, and Agent execution.
Django services own organization policy and PostgreSQL records through the ORM;
the Python worker calls those services from a separate process. Public APIs remain
in Django Ninja, with explicit organization-scoped request and response schemas.

Proposed extension for news: low-frequency news/announcement adapters run in the
existing Python worker, with source metadata and evidence revisions persisted
through Django services. This groups research-context processing with the
Intelligence Plane and avoids an additional deployable service. These adapters
do not collect exchange market data. Source-specific access and retention rules
must be established when sources are selected.

## Triggers and selection

| Trigger | Selection | Run identity |
| --- | --- | --- |
| Signal | Organization coverage, configured thresholds, data quality, deterministic ranking | Organization, research subject, trigger event, policy version |
| Daily digest | Eligible observations and validated reports in the configured period | Organization, stable schedule ID, digest period |
| On demand | Authorized member chooses a market or reviewed pair | Organization, client idempotency key |

On-demand requests return a job reference; expensive work runs in the worker.
Daily periods use a configured timezone with explicit UTC boundaries. A unique
period key prevents repeated scheduler ticks or restarts from creating duplicates.
Freeze the policy version on the job; editing a policy does not create a second
digest for an existing period. Schedule changes take effect at the next period
boundary. Catch-up work is bounded by configured lookback and budget.

Deduplicate exact triggers independently of subject-level cooldowns. Within a
cooldown, collect additional observations for the next eligible analysis. A
configured material-change rule can permit a new run. Reanalysis retains previous
reports and records the reason for the update.

Rank eligible candidates using deterministic metrics. Record selection and
suppression reasons so users can inspect why a market was or was not analyzed.
Thresholds, quality requirements, ranking parameters, and budgets are versioned
configuration; no default numerical values have been chosen yet.

## Evidence and tools

Each run freezes a research cutoff and a versioned context manifest containing:

- Outcome-specific market observations and computed metrics.
- Signal IDs, calculation versions, input windows, and quality flags.
- Market-rule revisions and reviewed cross-platform match revisions.
- Relevant source items, document revisions, URLs, timestamps, and association
  rationale; include contradictory evidence when available.
- Organization policy version and the tools' returned evidence references.

The cutoff applies to every tool query. Preserve metric inputs or immutable
snapshots and accessible evidence versions for the declared retention period.
Newly discovered material after the cutoff belongs to a later analysis.

Initial tools retrieve market metadata, historical metrics, signals, reviewed
comparisons, and indexed source evidence. Source refreshes happen before context
construction. Tool schemas bound query windows, result counts, and execution time.
Tenant context is enforced by the tool executor and is never selected by the LLM.

External documents are evidence, not executable instructions. The Agent receives
read-only tools and cannot change policies, grant access, execute trades, or send
external messages. Numeric facts in the report reference computed metric IDs;
the application renders their authoritative values.

## Structured report contract

Use Pydantic validation and explicit API schemas. The proposed report contains:

| Field | Meaning |
| --- | --- |
| `action` | `IGNORE`, `WATCH`, or `INVESTIGATE`; a research-priority decision |
| `confidence` | Value in `[0, 1]` expressing the Agent's stated confidence in its research-priority judgment; calibration is unestablished |
| `thesis` | Concise research interpretation |
| `key_signals` | References to stored signals and metrics |
| `claims` | Statements classified as observation, hypothesis, or externally supported explanation, with evidence IDs |
| `counter_evidence` | Conflicting observations or sources |
| `risk_flags` | Data gaps, weak matches, stale inputs, source limitations, or other research limitations |
| `follow_up` | Proposed observations or events to monitor |

Record run ID, organization, research subject, trigger, cutoff, context manifest,
model identifier, prompt/schema/tool versions, timestamps, token usage, and cost
status as execution metadata. `confidence` is not an event probability or a
calibrated accuracy estimate; UI labels must make its scope explicit.

Validate evidence references against the run context and reject unknown or
out-of-scope references. Check structured metric references and timestamps, and
bound any schema-repair attempts. A valid schema and valid citations do not prove
that a claim follows from its evidence; evaluation includes human-reviewed cases.

`follow_up` remains a research suggestion. Only authorized application policies
create schedules or change budgets. Daily digests cite underlying reports and
signals, retain uncertainty, and state when coverage or new evidence is limited.

## Durable task lifecycle

Proposed job states:

```text
PENDING → RUNNING → SUCCEEDED
                 → RETRY_WAIT → RUNNING
                 → FAILED
PENDING / RETRY_WAIT / RUNNING → CANCELLED
```

Keep jobs, attempts, policy versions, usage, and validated results in PostgreSQL.
Use short transactional claims, expiring leases, and worker heartbeats. Perform
network calls outside database transactions. Expired leases become eligible for
bounded retries; stale attempts cannot overwrite a later attempt's result.

Enforce trigger idempotency with database uniqueness and commit result publication
with job completion in one application transaction. Recheck cancellation and
lease ownership before publication. Cancellation stops new tool work and discards
late results; an already submitted provider call may still incur cost.

External LLM calls can be repeated after an ambiguous timeout or worker crash.
Use provider idempotency when available and track each attempt. Do not promise
exactly-once provider execution. Redis may accelerate coordination and updates;
losing it must not erase pending work or completed reports.

## Authorization and budgets

Initial proposed policy:

- OWNER sets the organization spending ceiling within platform limits; ADMIN
  manages research settings and allocations within that ceiling.
- MEMBER may request analysis within organization policy and budget.
- VIEWER reads permitted organization results.
- Django platform staff receive no implicit customer-workspace access.

Store organization limits for runs, concurrency, input/output size, tool calls,
and daily expenditure, plus a platform operating ceiling. Reserve capacity
transactionally before dispatch to prevent concurrent workers overspending the
configured allocation. Account for retries; retain or reconcile reservations for
ambiguous provider responses. Token caps and reservations bound admitted work;
provider billing reconciliation determines actual expenditure.

Record budget deferrals and failures in the research feed. The MVP delivers
results in-app. Email, chat, and webhook delivery require a separate feature and
explicit destination configuration.

## Verification before release

- Replay fixed observations to reproduce signal values and candidate selection.
- Verify cutoff enforcement with late-arriving news and revised market rules.
- Exercise duplicate triggers, simultaneous claims, crashes, expired leases,
  cancellation, bounded retries, and concurrent budget reservations.
- Check organization isolation in routes, tools, jobs, results, and exports.
- Reject invalid actions, confidence ranges, and evidence references.
- Use mocked LLM/source calls in normal tests and a small reviewed report dataset
  to assess evidence support, uncertainty, usefulness, repetition, and cost.
- Demonstrate that unavailable news or model services produce visible limitations
  while market collection and deterministic analysis continue.
