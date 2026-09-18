# Data quality audit — 18 September 2026

Read-only measurements at 10:18–10:21 Asia/Shanghai. The main ClickHouse
cutoff was `2026-09-18T02:18:27.277030Z`; PostgreSQL state and the follow-up
source checks were read shortly afterwards. Collection continues, so these
counts are a dated snapshot. No collector settings or production data changed.

## Assessment

The data supports pipeline development and bounded market research. It is not
yet sufficient to establish forecast improvement from fine-tuning. The limiting
factors are independent labeled events, reviewed evidence, historical continuity,
and execution data. Row count alone does not measure training readiness.

| Measure | Observed value | Interpretation |
| --- | --- | --- |
| Directory entries | 51,854 | Discovery metadata, not historical price series |
| Historical observations | 18,370 | 12,328 Polymarket; 6,042 Kalshi; logical rows queried with `FINAL` |
| Historical contracts / exchange events | 34 / 11 | Exchange events can represent the same real-world occurrence |
| Enabled distinct targets | 32 | 20 open contracts; 12 resolved contracts |
| History span | About 59 hours | Starts 15 September 23:18 local time; not continuous |
| Open-status rows with midpoint | 11,652 / 16,506, approximately 70.6% | Excludes closed/resolved rows from the denominator; not a forecast-eligibility rate |
| Current open contracts with usable price window | 14 / 20 | Existing 15-minute quality policy |
| Current open contracts with usable volume indicator | 11 / 20 | Includes effects of the numerical issue below |
| Current quality states | 10 ready, 5 limited, 5 blocked | Describe indicator availability only |
| Known binary outcomes | 12 contracts across 5 exchange events | 8 WON, 4 LOST, all Kalshi; insufficient independent evaluation units |
| Evidence items / revisions | 179 / 213 | 32 items have structured document text in their latest revision; 178 have excerpts |
| Market/evidence associations | 1,412 TOPIC_ONLY | All unreviewed; not supervised relevance labels |
| Event evidence reviews / research events | 0 / 0 | Event-level evidence labeling is not populated |
| Comparison reviews | 2 RELATED | Neither has a reviewing user attached; not verified equivalence labels |

## Reliability and completeness

- All ten long-running services were healthy. All 20 selected open contracts had
  observations no more than 56 seconds old at the primary snapshot.
- During the subsequent six-hour continuity check, maximum within-contract open
  sample gaps were 100 seconds for Polymarket and 71 seconds for Kalshi. Neither
  platform had a gap above 150 seconds in that window. This does not establish
  earlier continuity or complete exchange-tick coverage.
- Across the full open-status history, Polymarket has a maximum gap of 110,903
  seconds (30.8 hours); Kalshi has 47,011 seconds (13.1 hours). These queries
  exclude closed/resolved observations, including deliberately slow settled
  polling. Missing intervals must not be filled with invented observations.
- All observations have nonempty rules and reported volume. All lack native
  source event timestamps and normalized liquidity/depth. Receipt time establishes
  when we received a quote, not when the exchange last changed it.
- No crossed-book flags were present. Field presence and internal validation
  do not independently verify the exchange's economic accuracy.
- Six enabled news feeds recently succeeded with no consecutive failures. BEA's
  last result was partial. The CPI and employment BLS feeds remained disabled.

## Two different causes of current quality exclusions

### Numerical sensitivity in cumulative volume

The five contracts flagged `volume_counter_reset` at the main snapshot each had
one tiny downward change in the subsequent 20-minute inspection. For example:

```text
48,732,713.555604056 → 48,732,713.55560403
```

The change is about 0.00000003 in the adapter's reported USD units. This is a
floating-point-scale difference, not sufficient evidence of an economic reset.
The current [quality check](../python/quanthecy_analytics/quality.py) treats every
strict decrease as a reset. Raw storage should remain unchanged; derived volume
deltas and reset detection need a shared, documented numerical tolerance that
still detects meaningful decreases. The calculation in
[signals.py](../python/quanthecy_analytics/signals.py) must use the same policy.

This finding does not establish that every historical reset flag is false.
Constant-volume baselines are a separate limitation: a Z score is undefined when
its baseline variance is zero, even when the underlying observations are valid.

### Missing executable two-sided quotes

Stored raw responses confirmed missing or empty bids for the six contracts with
`missing_midpoint`: four Polymarket records lacked `bestBid`; two Kalshi records
had a zero YES bid and zero bid size. Their available asks do not justify inventing
a midpoint. Retain these contracts for coverage and applicable research tasks,
but exclude them from methods requiring a two-sided quote. Missing midpoint is
not evidence that their rules or settlement information are unusable.

## Training and evaluation blockers

1. **Outcome ingestion is incomplete.** The Polymarket branch in
   [adapters.rs](../services/market-data/src/adapters.rs) can recognize resolved
   status but currently emits `UNKNOWN` for the outcome and no resolution time.
   Kalshi labels exist, but only across five events. Price near zero or one must
   never substitute for a sourced final outcome.
2. **Event independence is limited.** Multiple thresholds, outcomes, platforms,
   and minute observations can all describe the same real-world event. Group
   these before train/validation/test splitting and before reporting uncertainty.
3. **Evidence is mostly unreviewed.** Topic associations and successful Agent
   reports do not constitute correct supervised answers. Structured text is
   available for only part of the news collection; excerpts are not full articles.
4. **Historical availability needs explicit treatment.** Frozen inputs must use
   the rules and document revisions actually available at the research cutoff.
   Exchange close time, information release time, and settlement time differ.
   `OPEN` status alone does not prove that an outcome was still unknown. Collector
   staging time also differs from downstream availability during delayed replay;
   inspect batch commitment records when reconstructing such periods.
5. **Trading simulation inputs are incomplete.** Quote snapshots without depth,
   fills, and aligned fee assumptions do not establish executable returns. Native
   source timestamps are also needed for strong claims about reaction speed.

## Recommended implementation order

These are proposed changes, not completed work.

1. Correct numerical volume handling, with tests for harmless precision noise,
   genuine resets, unit changes, and flat baselines. Version changed analytics so
   existing signals remain reproducible. Keep all original observations.
2. Complete versioned outcome ingestion with source identity, observed time,
   settlement status and exceptional outcomes. Record information release times
   where verifiable; unknown timing stays explicit. Add independent event grouping.
3. Build a bounded offline dataset exporter using ClickHouse repositories and
   Django-owned metadata/reviews. Freeze source IDs, revisions, cutoff, inclusion
   policy, code version and hashes. Separate model inputs from subsequent labels.
   Export accepted samples, exclusion reasons and an immutable manifest. Start
   with management commands and existing Django Admin review workflows.
4. Expand collection in measured batches toward more independent events with
   usable quotes and complete lifecycles. Continue following selected events to
   resolution; keep failed, illiquid and cancelled cases in coverage accounting.
   Match sampling cadence to the research horizon. Any historical backfill must
   retain its actual acquisition time and remain distinguishable from live data.
5. Build reviewed research-task examples and a prospective forecast benchmark.
   A first batch of 100 reviewed examples can test the annotation process before
   expanding toward 500–1,000; these are workload targets, not established
   sufficiency thresholds. Split by event and time, and require training labels
   to have been available by the training cutoff. Compare the unchanged local
   model, its version using retrieved evidence, and a later fine-tuned version
   on the same frozen inputs, alongside contemporaneous market probabilities.

For research-task training, score rule interpretation, relevance, citation support
and appropriate abstention. For outcome forecasts, use Brier/log loss and
calibration, report coverage and event-level sample counts, and retain abstentions.
With the current five labeled events, results are exploratory. Training should
follow a usable baseline and reviewed samples; a Chat Completions endpoint alone
does not provide the model weights, tokenizer or hardware needed for fine-tuning.
