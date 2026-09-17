# Versioned official Federal Reserve documents

The news worker now enriches the existing two official RSS feeds with the main
HTML text of monetary-policy releases and speeches. Both Polymarket and Kalshi
remain active; this change does not change market selection or trade execution.

## Collection and provenance

- Only HTTPS URLs on `www.federalreserve.gov` matching source-specific release or
  speech paths are fetched. No user-supplied arbitrary URLs, redirects, linked
  articles, embedded scripts, attachments or PDFs are followed.
- One document is processed per news-worker cycle (normally 10 seconds plus work).
  Requests time out after 10 seconds and read at most 1 MiB. Successful documents
  are checked again after 24 hours, or sooner when RSS content changes.
- A five-minute database lease with a unique token prevents stale workers from
  publishing after another worker has claimed the item. Network work takes place
  outside the transaction. Failure retries back off from 15 minutes to 24 hours;
  fixed error codes contain no proxy secrets or raw exceptions.
- The extractor recognizes the official article body column and title. Missing or
  changed layouts, non-HTML responses, invalid UTF-8, empty/short text and bodies
  over 120,000 characters fail explicitly, retaining the prior evidence.
  Nested attachment columns are part of the page layout, not separate article bodies.
- `EvidenceRevision.document` stores title, source URL, document kind, plain text,
  capture time, extractor version, and SHA-256 hashes of response bytes and text.
  `raw_document` retains the decoded source HTML for operator audit, never browser
  execution. It is excluded from public API responses and Agent context.

## Versions and historical research

An RSS change or an extracted-document change appends a new immutable evidence
revision. Changes to HTML navigation without changes to the extracted content do
not create duplicate revisions. The first representative HTML is retained for
that document version. Identical RSS refreshes do not overwrite or duplicate a
document-enriched revision; RSS changes on the same URL retain the last captured
text with its original capture time while scheduling a fresh check. URL changes
clear the document on the new revision until the new target is retrieved.

Publisher publication time, RSS observation time, and document capture time remain
distinct. Enrichment never backdates a document to the publication date. The API
selects only the latest revision observed by the requested cutoff, and excludes
future publication dates. Historical responses omit present-day collection status.
Unknown publication dates remain visible as such in RSS but are not automatically
scheduled for document retrieval in this initial policy.

## Product and operations

The evidence list labels each record as **Text captured** or **Feed excerpt only**.
Evidence detail shows the plain-text body, numbered paragraphs, capture time,
source/hash metadata and links to earlier saved versions. Speeches are explicitly
distinguished from committee decisions. A refresh failure shows retry status while
retaining the saved version. English/Chinese UI and day/night themes are supported;
the original document language is preserved.

Django Admin's existing evidence-item and evidence-revision views expose capture
status and the stored document/HTML under their existing permissions. No new
operator privileges or group assignments are introduced. Historical research
records remain append-only; existing raw-market-payload cleanup does not delete
document evidence.

`NEWS_DOCUMENTS_ENABLED=false` pauses HTML retrieval while retaining RSS and all
saved evidence. `NEWS_FEEDS_ENABLED=false` pauses both. Both flags default to true.
Deploy Django migration `research.0002_official_documents` before the new worker.

## Agent use and limits

Agent `context-v6` uses the exact visible evidence-revision IDs. For each of at most
eight associated entries, RSS excerpts are bounded to 800 UTF-8 bytes and document
passages to 1,800 bytes. At most three paragraphs are chosen by a deterministic
count of policy terms, with original paragraph numbers, excerpt truncation and
omission indicators. Source documents remain untrusted context, never instructions.
The existing stage budgets and schema/citation validation still apply; no automatic
LLM requests are introduced.

This is partial context, not a claim that an Agent read the entire document.
Passages may omit qualifications or contrary evidence; users can inspect the full
captured body. Existing `TOPIC_ONLY` associations remain unreviewed and do not imply
causality or that a speech concerns the selected meeting. Macro indicator series,
release surprises, ALFRED vintages, event-level relevance reviews, and forecast
evaluation are separate subsequent work.

The UI and Agent context explicitly distinguish captured release-page text from
linked material. In particular, a minutes publication notice does not include the
full minutes behind an HTML link or PDF attachment.

## Market data licensing remains unresolved

Kalshi was briefly paused, then restored at the user's request on September 16,
2026 (collection revisions 3 and 4, with audit records). Retaining an integration
does not establish rights for commercial redistribution. Kalshi's developer
agreement and Polymarket's institutional data-licensing requirements still require
assessment for the intended product and customers; no blanket commercial license
is claimed. Sources: [Kalshi agreement](https://kalshi-public-docs.s3.amazonaws.com/Kalshi-Developer-Agreement.pdf),
[Polymarket institutional data](https://institutional.polymarket.com/).

## Local verification, September 16, 2026

- Backend: 239 tests passed, including ClickHouse integration, document version
  isolation, source restrictions, retries and API timestamp round trips. Ruff,
  formatting, mypy and migration consistency checks passed.
- Frontend: 44 tests passed; ESLint, TypeScript and the production build passed.
- Migration applied and local Compose services deployed and healthy on the
  existing ports. All 30 current feed entries acquired their official page text,
  with no remaining collection errors after retrying nested attachment layouts.
- Browser verification covered Chinese/English UI, day/night text readability,
  expansion to 28 paragraphs, and old versions without later document content.
  Admin exposes capture status and read-only document/HTML versions.
- Evidence observation timestamps preserve all microseconds in API JSON. Using
  those values as historical cursors returns the selected version exactly.
- A real context-v4 contained eight document selections, 20 observations and
  34,021 bytes of model context; each document selection remained within 1,800
  UTF-8 bytes. No paid model request was made for this verification.
- Collection revision 4 remains applied, with 15 active targets per exchange.

Version-bound operator review and event dossiers are documented in [event-evidence.md](event-evidence.md).
