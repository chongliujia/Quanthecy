# Event dossiers and version-bound evidence

The first dossier covers the Federal Reserve's scheduled October 27–28, 2026
meeting. The dates are sourced from the [official FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm),
recorded as a schedule, not as a guaranteed future event or a known outcome.

## Data and review boundaries

- `ResearchEvent` identifies the shared research question and collection topic.
  It is separate from each exchange's own event ID.
- `EventDefinition` appends a version of the question, dates, scope and eligible
  feeds and discovery policy. Changing scope requires a new definition; previous scope remains
  available at its original observation time.
- `EventMarketLink` stores the normalized contract and outcome snapshot at linking
  time. It does not claim that the linked contracts are equivalent. The market
  workbench remains the place to inspect current settlement rules.
- `EventEvidence` is an automatic candidate for one exact event definition and one
  exact evidence revision. Discovery never approves relevance; each candidate saves its matching method, reasons and original text snippets.
- `EventEvidenceReview` appends an operator's relevance classification, rationale,
  original paragraph numbers, actor and timestamp. Direct relevance requires 1–5 valid original paragraphs or an exact
  12–1000-character quote from the saved feed title/excerpt. Background and unrelated
  classifications may omit citations. Direct relevance does not mean support for YES, causal
  attribution, or a calibrated forecast.

The review service locks the event, source item and candidate while validating
that both versions are current. Django Admin saves within a transaction, so a
stale form returns a validation error and cannot attach approval to a newer body.
Reviews cannot be edited or deleted through the application. Subsequent review
records supersede earlier judgments while preserving the history.

The news worker examines up to 500 unmatched, currently visible revisions and
creates up to 100 candidates per dossier, up to 20 dossiers per cycle. Existing
scopes keep `source-only-v1`. Opting into `fed-macro-v1` requires a new definition
with an explicit source list; media sources require this content policy.

For the Fed policy, saved titles, excerpts and captured original paragraphs must
contain Fed policy terms or US macroeconomic terms. Publication dates must fall
between 180 days before the scheduled start and seven days after its end. Unknown
dates remain flagged. Matching the event month/year raises review priority to 30;
Fed policy terms use 20, broader macro terms 10. These are ordinal review priorities,
not probabilities, confidence scores, causal links or relevance approvals. Up to
three original snippets are retained per candidate. Matching is English-only and
bounded; unmatched text, ambiguous wording and content beyond the scan limit can
be missed. No automatic sentiment interpretation is performed.

Discovery is idempotent across workers. A new document body or feed revision requires fresh review; the reader
marks an old candidate as superseded even before the next worker cycle. Changing
the event definition creates a new queue. No paid model call is part of discovery.

## Operator workflow

1. Open **Evidence review** in the bilingual Django console.
2. Filter pending candidates and inspect the event scope and numbered source text.
3. Follow **Review this version**, select direct/background/unrelated, explain the
   relationship and limitations, and enter paragraph numbers such as `[2, 4]` or
   quote the saved feed title/excerpt exactly.
4. Independently choose **undetermined / supports / opposes**. Directional judgments
   require direct relevance and a selected contract/outcome from this event. The
   form shows saved settlement rules. Changed rules/outcomes block new directional
   judgments against the old link; existing judgments retain their historical target.
   The current link model does not silently replace that saved target; refreshing
   linked rule snapshots is a separate operator workflow not implemented here.
5. Save. The immutable review is immediately available to the event API and future
   Agent contexts. Refresh the frontend or wait for its one-minute refresh.

Only staff with `research.add_eventevidencereview` can submit reviews. Existing
operator groups and memberships are not changed by this feature. Normal workspace
ownership does not confer platform review permission. The public authenticated API
is read-only and exposes neither reviewer email nor raw HTML.

Initialize the example after migrations and the existing collection topic import:

```sh
python apps/backend/manage.py initialize_fed_event --expand-news
python apps/backend/manage.py news_quality --event fed-october-2026
```

The initialization command is idempotent, links the topic's collected contracts with saved rules,
and creates pending candidates. It does not manufacture a human approval. The `--expand-news` option appends a definition with curated official/media sources
and the Fed policy; old reviews stay on the old scope. `news_quality` is read-only:
it reports last-poll counts and the content-match share in up to 100 saved entries
per source. It measures retrieval coverage, not matching precision or forecast accuracy. Source
collection itself continues to be governed by the existing collection plan.

## Customer and Agent behavior

- `#/events` lists dossiers; `#/events/fed-october-2026` shows scope, counts,
  review filters, cited passages, saved contract rules and the last 50 changes.
- A historical cutoff applies to scope, links, evidence, review and change records.
  Changes are ordered by platform observation time, not inferred market impact.
- Evidence and report links retain microsecond precision and open the exact
  revision. `paragraph=N` expands and highlights the original paragraph.
- `context-v6` prioritizes reviewed evidence and records review IDs, event-definition
  IDs and original paragraph numbers in the frozen report inputs. Unrelated
  evidence is excluded for its linked event unless another linked event has a
  positive review. Legacy topic matches remain explicitly unreviewed context.
- Operator-selected text is bounded to three passages / 1,800 UTF-8 bytes, with
  truncation disclosed. Full original text remains available through the link.
- `research-team-v6` / skills `1.5.0` require a cited, current, directly reviewed
  evidence revision with official provenance and cited original body paragraphs before allowing a conditional probability estimate, in addition
  to the existing quote, settlement and data-quality gates. This is a minimum
  eligibility check, not proof of predictive value. Without it, qualitative research
  can proceed but probability output must be `ABSTAIN`.
- Candidate cards expose matching reasons, original snippets, exact outcome stance
  and bounded changes from the previous saved revision. Added/removed paragraphs
  link to their respective versions; first body capture is not automatically a new
  publisher statement. This comparison is not relative to a user's last report.
- Frozen Agent evidence contains the same version changes and saved outcome stance.
  A stance applies only to its selected market and matching saved outcome/rules.
  Media excerpts alone never unlock probability estimates. The Agent is prompted
  to explain changed evidence, counter-evidence and unresolved gaps; output quality
  still requires evaluation. No paid model run is triggered by ingestion or review.

Existing reports are not rewritten. The relational graph now records event,
contract, source, paragraph, review and explicitly targeted support/opposition.
It does not infer causal edges, measure historical forecast accuracy, cluster
syndicated reporting or ingest complete linked PDF minutes.
