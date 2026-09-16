# Single-market intelligence team

Implemented as an on-demand extension of the existing Django job and Python
worker. The UI defaults to expert collaboration; quick single-Agent research and
existing reports remain available. No model calls occur on page load or save.

## Research workflow

| Skill | Scope | Inputs from other experts |
| --- | --- | --- |
| Quantitative analyst | Computed movement, spread, volume, signal reliability | None |
| Event intelligence analyst | Versioned evidence, timing, provenance, missing catalysts | None |
| Investment research analyst | Contract settlement, probability basis, reviewed comparisons | None |
| Risk reviewer | Challenges, conflicting claims, invalidation conditions | First three experts |
| Research lead | Cited synthesis, disagreements, conditional forecast or abstention | All four experts |

The first three specialists reason independently. Calls execute in bounded
sequence to avoid bursts of requests; independence concerns their input context,
not concurrency. Every expert currently uses the workspace's saved model. A team
does not provide independence between different underlying model families.

Skills are trusted application definitions in
`python/quanthecy_analytics/intelligence.py`. Each declares its ID, version, role,
permitted reference kinds and dependencies. Adding or changing a skill requires a
versioned code change and tests. There is no arbitrary code execution, uploaded
prompt execution, autonomous browsing or trading. The catalog is exposed through
the organization-scoped `GET /agent/skills` endpoint.

## Context and working memory

1. Freeze observations known at the research cutoff, the last 20-minute analytical
   window, contract rules, deterministic metrics, signals, up to eight associated
   news revisions and five reviewed comparisons.
2. Persist original observations for audit. Models receive references and computed
   metrics, not the raw observation series.
3. Select whole references for each skill. Evidence is capped at 32,000 UTF-8 bytes
   per stage; omitted IDs are explicit. Required market/rule records never silently
   truncate. The entire stage packet, including schema and peer memory, is capped
   at 80,000 UTF-8 bytes. These are byte limits, not tokenizer-specific token counts.
4. Validate specialist outputs before sharing them. Memory consists of a short
   conclusion, up to four findings, three challenges, limitations and observations
   to monitor. Each specialist output is capped at 14,000 bytes. No raw transcript
   or model scratchpad is stored or passed on. Referenced peer evidence must be
   present in the receiving stage's scope.
5. Save per-stage source IDs, omissions, dependencies, input/system hashes, skill
   version and skill definition, timestamps, usage and validated output. The full frozen context and
   original observation hash stay on the organization-owned run. There is no
   cross-run retrieval or cross-tenant memory.

Source text and peer conclusions are untrusted data. A peer conclusion is not a
new independent source. Every claim must cite IDs from that stage's allowed
context. Citation and schema checks cannot establish semantic truth; human review
and a labeled evaluation dataset are still needed.

## Forecast semantics

The final report can contain an uncalibrated probability for the **YES outcome at
contract resolution**, with an ordered subjective range, cited rationale,
assumptions and invalidation conditions. This is separate from both the observed
market probability and confidence in research priority. It is not a prediction of
the next quote, a statistical confidence interval or a trade recommendation.

The deterministic eligibility gate requires fresh, valid midpoint history, an
open contract with rules and a future closing time, and associated event evidence.
An estimate must cite event evidence. Failing this gate requires `ABSTAIN` with
null probabilities. Eligibility is necessary, not sufficient: the lead can still
abstain after reviewing relevance and source quality. Missing probabilities never
become zero.

Forecasts remain frozen with their report/cutoff/model version. The platform does
not yet match settled outcomes, calculate Brier scores or claim forecast accuracy.
Outcome reconciliation, calibration and rolling evaluation are a subsequent
feature, separate from this initial inference workflow.

## Report format compatibility and diagnostics

`research-team-v2` / skills `1.1.0` use a 600-character specialist claim limit in
both the schema sent to the model and the validator. The prompt supplies a JSON
example and explicit permitted citation IDs; the schema restricts references to
the stage's scope. Field names and enum values remain in English in Chinese reports.

Local parsing accepts one complete JSON object, optionally wrapped in a single
JSON Markdown fence. It rejects truncation, duplicate keys, trailing prose and
non-finite JSON constants. The specialist memory budget measures canonical UTF-8
content after validation, so whitespace and escaped Chinese cannot inflate the
same report beyond its budget. It never drops unsupported fields, invents missing
content or changes evidence references to make a response pass.

Failed runs now store bounded, redacted `validation_errors` on the run and failed
stage: schema field paths and fixed error categories only. These are exposed in
the UI; raw model text, values, unknown citation IDs and provider-controlled extra
field names are not retained in diagnostics. Migration
`agents.0003_validation_diagnostics` leaves older failures without detailed issues;
the UI explicitly states those details were not recorded. No model repair call or
automatic retry is introduced. Output examples follow the
[DeepSeek JSON output guidance](https://api-docs.deepseek.com/guides/json_mode/).

## Execution, quota and compatibility

`POST /agent/markets/{market_id}/runs` accepts `workflow: "team" | "single"` and
`language: "zh" | "en"`. Existing API callers default to single research in English.
Idempotency includes workflow, language, market and an explicit cutoff.

A team reserves five model requests at admission; a single report or connection
test reserves one. The UTC daily limit counts reserved calls, conservatively
including unused capacity after failure/cancellation. It is not a currency budget.
Actual attempted calls and returned tokens are saved separately. Each stage uses
the configured per-request output limit; there are no automatic retries.

Each stage renews the current lease and rechecks organization membership and model
configuration before sending. Cancellation, revocation, changed configuration,
invalid evidence or provider failure prevents further stages and final
publication. Completed expert findings remain visible as intermediate results.
Expired jobs fail without automatic replay. Final publication rechecks lease and
configuration under the workspace lock.

Migration `agents.0002_research_team` adds workflow, report language, reserved
calls and step records without replacing existing reports or credentials.

## Verification

Mocked-provider tests cover five-stage execution, independent expert inputs,
critic/lead memory, citation scope, full input retention, language, quota admission,
idempotency, provider errors, cancellation, membership/configuration changes,
tenant isolation, abstention and conditional forecast validation. UI tests cover
explicit request initiation, five-call disclosure, quota blocking and the
distinction between market probability and abstention.

No paid model calls are required by these checks. Current source coverage remains
the existing collected market data and indexed official feeds; this feature does
not add broad financial-news search or unrestricted web research.

The full regression run passed 137 Python tests (two opt-in ClickHouse tests
skipped) and 31 frontend tests. Ruff, mypy, lint, migration consistency and both
production image builds passed. Isolated Chrome checks verified the actual skill
catalog and disabled-model state, then intercepted the analysis API with explicitly
labeled synthetic responses to check report rendering, citation expansion and a
390px mobile viewport. No generation request reached the backend in UI verification.

Synthetic UI previews: [expert findings](screenshots/intelligence-experts.png),
[forecast abstention](screenshots/intelligence-report.png) and
[mobile workspace](screenshots/intelligence-mobile.png). These are interface test
examples, not actual model forecasts or analyses of the visible market.
