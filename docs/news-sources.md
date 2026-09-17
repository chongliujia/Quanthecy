# Curated news sources

Quanthecy collects official economic announcements and selected business-news RSS
feeds in the existing Python news worker. It stores provenance and versions in
PostgreSQL and serves them through Django Ninja. It does not need a paid news API
or X credentials for this collection set.

## Initial registry

| ID | Publisher / coverage | Default | Public feed |
| --- | --- | --- | --- |
| `fed-monetary` | Federal Reserve monetary policy | Enabled | [RSS](https://www.federalreserve.gov/feeds/press_monetary.xml) |
| `fed-speeches` | Federal Reserve speeches | Enabled | [RSS](https://www.federalreserve.gov/feeds/speeches.xml) |
| `fed-testimony` | Federal Reserve testimony | Enabled | [RSS](https://www.federalreserve.gov/feeds/testimony.xml) |
| `bea-releases` | BEA economic releases, including GDP and personal income/outlays | Enabled | [RSS](https://apps.bea.gov/rss/rss.xml) |
| `bbc-business` | BBC business reporting | Enabled | [RSS](https://feeds.bbci.co.uk/news/business/rss.xml) |
| `cnbc-economy` | CNBC economy reporting | Enabled | [RSS](https://www.cnbc.com/id/20910258/device/rss/rss.html) |
| `bls-employment` | BLS Employment Situation | Paused | [RSS](https://www.bls.gov/feed/empsit.rss) |
| `bls-cpi` | BLS Consumer Price Index | Paused | [RSS](https://www.bls.gov/feed/cpi.rss) |

On 2026-09-17 the six enabled endpoints returned HTTP 200 and parsed RSS in both
host and backend-container probes. Both BLS endpoints returned HTTP 403 in the host probe,
so they start paused. This is a connectivity observation, not an uptime guarantee.
An operator can enable them after verifying access in their deployment. No access
controls are bypassed. A newer installation probe may give different results.
The container probe found four duplicate BBC links and one BEA link without an
HTTPS scheme; these were deduplicated and rejected respectively.

The BLS and BEA adapters ingest **release announcements and feed excerpts**; they
do not implement a structured economic time-series API or extract numerical
indicators from prose. FRED, paid wire services, X and Telegram are not part of
this release. Publisher terms remain separate from Quanthecy's code license.

## Operation

Starting `news-worker` initializes the registry idempotently. It preserves existing
operator choices. In **Admin → News sources**, operators with
`research.change_evidencesource` can pause/resume a source and configure a polling
interval from 300 to 86400 seconds (default 900). A reason is required and the
change appears in the platform audit trail. The source URL and publisher identity
are read-only: adding an endpoint requires a reviewed change to
`apps/backend/quanthecy/research/feed_registry.py`.

The standard operator-role setup command includes source viewing for data viewers,
and viewing/changing for data administrators. Existing group memberships and
permissions are not changed by a schema migration or worker startup; administrators
can deliberately rerun `setup_operator_roles` to adopt the revised role definitions.

The admin and customer source-status views distinguish paused, pending, healthy,
partial, empty, retrying and overdue collection. They expose last check/success,
accepted/rejected/duplicate counts, undated counts, latest publication time and the
configured cadence. An old publication can be normal for a monthly release feed;
successful polling and recent publication are separate measures. These are current
operational states even when the evidence list uses a historical research cutoff.

`NEWS_FEEDS_ENABLED=false` stops all feed and document collection.
`NEWS_PROXY_URL` supplies an optional deployment egress proxy. Requests use only
registered HTTPS endpoints, reject redirects, time out after ten seconds, and read
at most 2 MiB. Parsing forbids XML DTDs/entities and supports RSS 2.0 and Atom.
Up to 100 entries per response are processed; larger feeds show partial coverage.
Article links must match that source's exact approved host list. Reading a feed
does not cause arbitrary linked pages to be fetched.

Conditional requests use ETag / Last-Modified. After a failure the next attempt
requests a fresh body to re-evaluate coverage and quality. Failures preserve stored evidence,
use exponential backoff (up to six hours), and honor bounded `Retry-After` for
HTTP 429/503 (up to one day). Error messages do not include proxy credentials or
raw response bodies. Database leases coordinate worker instances. Editing source
controls invalidates an in-flight feed response so it cannot publish under an old
configuration. Pausing does not revoke already collected research evidence.

## Data semantics and limits

- Strip known tracking parameters and fragments; preserve other query parameters.
  Deduplicate GUIDs and canonical article URLs within each source. A changed GUID
  for an existing source URL reuses the record; changed content appends a revision.
  This does **not** cluster differently worded syndicated stories across publishers.
  Multiple publishers must not automatically be counted as independent confirmation.
- Store source-provided publication time separately from first observation and
  revision observation. Future-dated entries are rejected for that poll. Missing or
  invalid publication times remain null and are visibly flagged. Atom `updated`
  never substitutes for `published`.
- Keep bounded original feed fields in each new revision for operator inspection:
  title (1000 characters), description (4000), link (2000), identity (1000), and
  publication/update strings (200). This is a field snapshot, not a byte-for-byte
  archive of the entire XML response. Existing revisions are not backfilled.
- Official and media provenance appear in the API, bilingual UI and frozen Agent
  context. Media reports stay secondary material. Full-page text capture remains
  restricted to the existing Fed monetary-release and speech adapters; other
  sources explicitly show feed-only coverage, including in historical views.
- Fed-titled markets can receive unreviewed macro-topic candidates from the listed
  US official sources and media entries with explicit Fed/US macro wording.
  Discovery examines at most 500 latest visible revisions and selects at most 100
  candidates for at most 100 markets. It does not approve causal explanations or
  support for a contract outcome. Rejected associations remain rejected.
- Event dossiers continue to use explicitly versioned official-source selections
  and human review. Adding news sources does not expand an existing event definition
  or enable Agent probability estimates without the existing evidence gates.

The existing retention policy remains append-only with no automatic expiry.
Feed polling can miss stories, changes or deletions between requests; it does not
provide a complete historical archive or a seconds-latency newswire.

## API and verification

- `GET /api/v1/research/sources`: authenticated source registry and current health.
- `GET /api/v1/evidence?kind=OFFICIAL|MEDIA&source=…`: filter by type and source;
  existing search, pagination and historical cutoff behavior remain available.
- Evidence responses add `source_kind`, `quality_flags` and `document_supported`.
  Source configuration is an operator-only Django Admin action.

Offline tests cover hostile links and XML, RSS/Atom dates, duplicate identities,
history preservation, conditional requests, rate-limit recovery, paused/in-flight
workers, permissions, media provenance and research relevance. Live connectivity
is checked separately; normal tests never require publisher or LLM requests.
