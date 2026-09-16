# Platform administration

Quanthecy uses Django Admin at `/admin/` for platform operators. Customer workspace
roles do not grant platform access. PostgreSQL stores operation requests and audit
records; the analytical repository accesses ClickHouse directly.

## Setup

After rebuilding and running the deployment (which applies migrations):

```bash
docker compose exec backend python apps/backend/manage.py createsuperuser
docker compose exec backend python apps/backend/manage.py setup_operator_roles
```

The second command creates or resets three standard Django groups. It does not
create users or assign access. A superuser grants **Staff status** and the relevant
group on the user's admin page. Use separate operator identities from customer
workspace owners.

| Group | Access |
| --- | --- |
| Quanthecy data viewer | Collection status, market metadata, raw JSON, deletion job status |
| Quanthecy data administrator | Collection status, raw JSON, deletion requests, operation audit |
| Quanthecy user support | View customer accounts/workspaces; change customer passwords and account status; view operation audit |

Only superusers can change platform flags, groups or user permissions through the
user admin, or edit another operator's account/password. These standard groups do
not grant group administration, user deletion, or organization membership editing.
Superusers can create accounts with Django's normal password validation.

## Operator console

The console defaults to Simplified Chinese. Use **中文 / EN** in the header to switch
language on the current page without losing its URL filters. The preference persists
in an HttpOnly, SameSite cookie for one year. Language switching is CSRF-protected
and only redirects within `/admin/`; it does not change the customer-facing API's
language or preferences.

The sidebar groups **Overview**, **Collection health**, **Raw observations**, markets,
research resources, users, workspaces, cleanup jobs and audit records. Navigation and
summary cards follow the operator's Django permissions. **All resources** provides
access to additional registered admin models. On smaller screens, use the menu button
to open the navigation; wider tables scroll within their own container.

The overview displays live market/user counts, queued and failed cleanup jobs,
exchange freshness and recent audit activity. Refresh to update status. User tables
support email search and access/status filters; cleanup jobs support request ID,
operator email and reason search. Forms and operations retain Django's session,
CSRF and server-side permission checks.

## Collection health

The admin home links to **Collection health / 数据采集**. It shows:

- PostgreSQL, Redis and ClickHouse connectivity;
- per-exchange observation age, fresh/total market counts and recent collector errors;
- each collector's latest committed batch, PostgreSQL reconciliation checkpoint,
  backlog and last checkpoint update;
- pending/running maintenance requests.

A positive batch lag means reconciliation remains outstanding. A negative lag or
checkpoint with missing ClickHouse history requires investigation of storage or
restore consistency. Redis telemetry can expire or become unavailable independently
of durable history. Freshness reflects the configured market sample, not exchange-wide
coverage. Refresh the page to update its values; this release does not send alerts.

The Rust journal/retry and deterministic reconciliation flow remain the collection
path. Maintenance runs in a separate `maintenance-worker` container. Its heartbeat
advances with processing cycles; a stalled worker is unhealthy after 90 seconds.
Existing collection tests plus the raw-cleanup integration test check that retained
envelopes still reproduce signals and the next batch can advance after cleanup.

## Inspecting and clearing exchange JSON

Open **Raw observations / 原始数据**. Filter by Polymarket/Kalshi, UTC
time interval and optional Quanthecy market UUID. The interval is start-inclusive,
end-exclusive and at most seven days. Pages contain 50 observations; narrow the
range after 5,000 offsets. Detail pages escape all source text and display at most
131,072 characters of each JSON field, with a truncation notice.

Clear raw JSON through this workflow:

1. Inspect a range and select **Preview cleanup for this range / 预览当前范围清理**.
2. Review eligible/protected/already-empty counts. Eligible requests contain
   1–10,000 logical observations; at most 100 collector checkpoints are supported.
3. Enter a reason, check the confirmation box and queue the request.
4. Inspect **Cleanup jobs / 清理任务** for state and error codes, and **Audit trail / 操作审计** for request/completion/failure records.

The preview is signed, bound to its operator, valid for 15 minutes and freezes
collector checkpoints. Repeating the same confirmation creates only one job.
The maintenance worker submits a ClickHouse mutation and polls it. HTTP requests
do not wait for background part rewrites. Permissions are checked again before
submission. Revoking access cannot undo a mutation already accepted by ClickHouse.

Only `raw_payload` is cleared. Normalized envelopes, observation rows, ingestion
batch markers, market metadata, signals and Agent reports remain. This preserves
deterministic analytics and history exports, but removes the original exchange JSON
needed to investigate parser behavior. It is not deletion of all derived information.

A row is eligible only when `batch_id` is **strictly less than** that collector's
reconciled PostgreSQL checkpoint. The latest reconciled batch and unreconciled rows
are protected because the current durable journal could still replay them. The last
batch of a retired collector therefore remains protected in this version.

Jobs use PostgreSQL leases and fencing tokens. The operation UUID is retained in the
ClickHouse mutation command so a worker can discover an accepted submission after
a lost HTTP response. The worker polls active mutations, including temporarily
failed ones, without repeatedly submitting them. It reports success only when its
mutations are complete and eligible payloads are empty. After three unconfirmed
submission attempts it records `submission_unconfirmed` for operator investigation.
Persistent mutation errors remain running with `storage_mutation_retrying`.
Do not remove ClickHouse mutation records while related jobs are outstanding.

Logical clearing is not secure erasure of old disk blocks, backups or exported files.
Coordinated restores must preserve collector journal/checkpoint/history consistency;
restoring an older backup can restore cleared JSON, requiring the retention operation
to be reapplied. There is no automatic retention schedule or bulk deletion of normalized
history in this release.

## Account status

Use **Users → Manage status** and provide a reason. Disabling an account prevents
subsequent authenticated requests and cancels pending/running Agent jobs. A model
request already sent may still incur its provider charge; disabled users cannot
publish a new result through the worker. Existing reports and memberships remain.

An operator cannot disable their own account. A customer's last active organization
owner cannot be disabled until ownership is transferred. Concurrent owner status
changes and membership changes serialize on the organization; an inactive owner
does not satisfy the ownership requirement. Organization creation also rechecks the
owner's status under a user row lock.

Re-enabling restores authentication eligibility but does not restart cancelled jobs.
The admin exposes no destructive user deletion. Account status and raw cleanup have
dedicated append-only admin audit views; normal password/permission edits retain
Django's built-in admin log. Audit records do not contain passwords or raw JSON.

## Intelligence roadmap boundary

These changes establish the operations foundation; they do not implement a knowledge
graph. A useful next product slice is an evidence-backed event relationship view:
events, contracts, settlement rules, dated observations and evidence links. Each
proposed relation should carry source, validity dates, confidence and review state.
Start from existing PostgreSQL entities and reviewed comparisons, without adding a
graph database before query needs justify it.

Deterministic analytics should identify measurable divergence or response timing;
Agents can then propose relationships, explain evidence, surface alternative
interpretations and produce research hypotheses. The differentiated output should
answer **what changed, which related contracts may be affected, what supports the
link, and what would invalidate it**. Evaluate those hypotheses against later
observations with explicit time cutoffs. A shared topic alone does not establish
causality, contract equivalence or a tradable opportunity.

## Validation

`apps/backend/tests/test_console.py` checks language persistence, filtered redirects,
CSRF, public-API language isolation, permission-aware navigation and bilingual page
rendering. Desktop/mobile browser checks cover the deployed console.

`apps/backend/tests/test_operations.py` exercises permissions, CSRF, account/owner
protection, concurrent disabling, signed previews, retries and lease fencing.
`tests/test_history_integration.py` includes a real ClickHouse cleanup test using a
unique temporary database:

```bash
QUANTHECY_TEST_CLICKHOUSE_URL=http://localhost:8123 uv run pytest tests/test_history_integration.py
```

The opt-in test expects the repository's test ClickHouse credentials and a local
PostgreSQL test configuration. It never contacts an exchange or an LLM.
