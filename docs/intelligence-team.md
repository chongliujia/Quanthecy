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

`context-v5` additionally includes bounded passages from captured official documents,
using the exact evidence version known at the cutoff. See
[official-evidence.md](official-evidence.md) for source restrictions, paragraph
selection, versioning and limits. Old run contexts remain immutable.

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
   conclusion, up to four findings, three challenges and three observations to
   monitor. All specialists, including event intelligence and risk review, can
   supply up to twelve limitation groups. Each specialist
   output is capped at 14,000 bytes. No raw transcript
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

`research-team-v5` / skills `1.4.0` keep the 600-character specialist claim limit
consistent between prompts, schemas and validation. All specialists now allow
twelve limitation groups; the previous four-item cap for independent specialists
caused the September 16 event-intelligence failure despite adequate output tokens.
Examples, allowed citation IDs and `output_limits` still ask the model to comply
with the canonical schema.

Before stage validation, a bounded local formatter may group consecutive strings
in `limitations`, `watch_for`, `risk_flags` or `follow_up` when only their item count
exceeds the schema limit. It handles at most 64 original items, preserves every
original character and item order, and adds bullet separators. It does not rewrite,
deduplicate, truncate, or use another model request. Each resulting group must fit
the original per-item text limit, and the complete specialist result must still fit
14,000 UTF-8 bytes. If grouping cannot fit losslessly, validation still fails.

Claims, citations, signals, forecast fields and other fields are never grouped or
repaired. Normal schema, reference and forecast checks run after grouping. Successful
steps record `format_adjustments` (field, original count, grouped count, method), which
the UI displays. Invalid outputs are never published merely because a text-list
format could be corrected. The stage API uses the same canonical output schemas.

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

The configurable output allowance is 256–65,536 tokens per request. The settings
API advertises the server ceiling, and the UI uses it for validation. Existing
workspaces keep their value unless an owner changes it; connection tests still
request at most 256 tokens. A provider/model may support a lower ceiling. Some
providers count reasoning in this allowance, so it is not the final report size
or the amount of input evidence. Structured report and evidence budgets remain
independent. For the local user's enabled `deepseek-flash` connection, the requested
increase is to 32,768 tokens, below the current
[official model output limit](https://api-docs.deepseek.com/quick_start/pricing/).

Requests above 8,000 tokens have a 300-second socket timeout and a 320-second
subprocess deadline. Their run lease exceeds that deadline by 60 seconds, for
both single and team research. Smaller requests retain the previous 40/60-second
timeouts. Response reads scale with the token budget, including escaped Unicode
and provider reasoning, with an absolute 8 MiB ceiling. Only returned report text
and token counts leave the provider adapter; provider reasoning is not persisted.
Cancellation and worker shutdown can still terminate the child process promptly.

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

Regression coverage includes independent specialists with twelve limitations,
lossless Unicode grouping of 13, 36 and 64 original items, ungroupable items,
invalid citations/types, forecast gates, whole-result memory limits, complete
five-stage execution and public API serialization. Both the risk review and final
synthesis retain all caveats without a sixth model request. UI checks cover Chinese
system warnings and visible grouping notices. Existing failed reports remain
failed: their rejected raw output was not retained and cannot be reconstructed.

Earlier isolated Chrome checks verified the actual skill
catalog and disabled-model state, then intercepted the analysis API with explicitly
labeled synthetic responses to check report rendering, citation expansion and a
390px mobile viewport. No generation request reached the backend in UI verification.

Synthetic UI previews: [expert findings](screenshots/intelligence-experts.png),
[forecast abstention](screenshots/intelligence-report.png) and
[mobile workspace](screenshots/intelligence-mobile.png). These are interface test
examples, not actual model forecasts or analyses of the visible market.

Event dossier reviews and probability eligibility are documented in [event-evidence.md](event-evidence.md).
