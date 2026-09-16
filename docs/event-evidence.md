# Event dossiers and version-bound evidence

The first dossier covers the Federal Reserve's scheduled October 27–28, 2026
meeting. The dates are sourced from the [official FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm),
recorded as a schedule, not as a guaranteed future event or a known outcome.

## Data and review boundaries

- `ResearchEvent` identifies the shared research question and collection topic.
  It is separate from each exchange's own event ID.
- `EventDefinition` appends a version of the question, dates, scope and eligible
  official feeds. Changing scope requires a new definition; previous scope remains
  available at its original observation time.
- `EventMarketLink` stores the normalized contract and outcome snapshot at linking
  time. It does not claim that the linked contracts are equivalent. The market
  workbench remains the place to inspect current settlement rules.
- `EventEvidence` is an automatic candidate for one exact event definition and one
  exact evidence revision. Matching by official source never approves relevance.
- `EventEvidenceReview` appends an operator's relevance classification, rationale,
  original paragraph numbers, actor and timestamp. Direct relevance requires 1–5
  valid original paragraphs. Background and unrelated classifications may omit
  paragraph citations. Direct relevance does not mean support for YES, causal
  attribution, or a calibrated forecast.

The review service locks the event, source item and candidate while validating
that both versions are current. Django Admin saves within a transaction, so a
stale form returns a validation error and cannot attach approval to a newer body.
Reviews cannot be edited or deleted through the application. Subsequent review
records supersede earlier judgments while preserving the history.

The news worker discovers up to 100 new candidates per dossier, up to 20 dossiers
per cycle, using the existing registered official feeds. It is idempotent across
workers. A new document body or feed revision requires fresh review; the reader
marks an old candidate as superseded even before the next worker cycle. Changing
the event definition creates a new queue. No paid model call is part of discovery.

## Operator workflow

1. Open **Evidence review** in the bilingual Django console.
2. Filter pending candidates and inspect the event scope and numbered source text.
3. Follow **Review this version**, select direct/background/unrelated, explain the
   relationship and limitations, and enter paragraph numbers such as `[2, 4]`.
4. Save. The immutable review is immediately available to the event API and future
   Agent contexts. Refresh the frontend or wait for its one-minute refresh.

Only staff with `research.add_eventevidencereview` can submit reviews. Existing
operator groups and memberships are not changed by this feature. Normal workspace
ownership does not confer platform review permission. The public authenticated API
is read-only and exposes neither reviewer email nor raw HTML.

Initialize the example after migrations and the existing collection topic import:

```sh
python apps/backend/manage.py initialize_fed_event
```

This command is idempotent, links the topic's collected contracts with saved rules,
and creates pending candidates. It does not manufacture a human approval. Source
collection itself continues to be governed by the existing collection plan.

## Customer and Agent behavior

- `#/events` lists dossiers; `#/events/fed-october-2026` shows scope, counts,
  review filters, cited passages, saved contract rules and the last 50 changes.
- A historical cutoff applies to scope, links, evidence, review and change records.
  Changes are ordered by platform observation time, not inferred market impact.
- Evidence and report links retain microsecond precision and open the exact
  revision. `paragraph=N` expands and highlights the original paragraph.
- `context-v5` prioritizes reviewed evidence and records review IDs, event-definition
  IDs and original paragraph numbers in the frozen report inputs. Unrelated
  evidence is excluded for its linked event unless another linked event has a
  positive review. Legacy topic matches remain explicitly unreviewed context.
- Operator-selected text is bounded to three passages / 1,800 UTF-8 bytes, with
  truncation disclosed. Full original text remains available through the link.
- `research-team-v5` / skills `1.4.0` require a cited, current, directly reviewed
  evidence revision before allowing a conditional probability estimate, in addition
  to the existing quote, settlement and data-quality gates. This is a minimum
  eligibility check, not proof of predictive value. Without it, qualitative research
  can proceed but probability output must be `ABSTAIN`.

Existing reports are not rewritten. This is the first relational graph of event,
contract, source, paragraph and review. It does not yet infer causal edges, label
support/opposition to an explicit outcome, calculate historical forecast accuracy,
or ingest complete linked PDF minutes. Those need separate data and validation.
