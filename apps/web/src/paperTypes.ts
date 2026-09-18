export type PaperAccount = {
  id: string; platform: string; strategy: string; initial_cash: string; cash: string; reserved_cash: string
  equity: string | null; realized_pnl: string; unrealized_pnl: string | null; fees: string; max_drawdown: string
  unpriced_positions: number; equity_at: string | null; fills: number; orders: number
  equity_history: { at: string; equity: string | null }[]
}
export type PaperOrder = {
  id: string; account_id: string; market_id: string; title: string; side: string; status: string; reason: string
  quantity: string; filled_quantity: string; limit_price: string; created_at: string; finished_at: string | null
}
export type PaperLabData = {
  experiments?: { id: string; name: string; version: string; running: boolean; created_at: string }[]
  is_latest?: boolean; review_summary?: PaperReviewSummary | null; recent_reviews?: PaperReview[]
  id: string; name: string; running: boolean; version: string; settings: Record<string, unknown>; checked_at: string | null
  created_at: string; error_code: string; collector: { checked_at?: string; errors?: number; successful?: number; markets?: number }
  market_count: number; accounts: PaperAccount[]
  positions: { id: string; account_id: string; market_id: string; title: string; quantity: string; cost_basis: string; opened_at: string }[]
  recent_orders: PaperOrder[]
  recent_decisions: { id: string; account_id: string; market_id: string; title: string; action: string; reason: string; created_at: string }[]
}
export type PaperOrderDetail = PaperOrder & {
  inputs: Record<string, unknown>; execution_quote: { received_at: string; fee_rate: string | null; fee_model: string; source: string } | null
  fills: { quantity: string; price: string; fee: string; cash_delta: string; realized_pnl: string; created_at: string }[]
  replay_matches: boolean | null
}
export type PaperCandidate = { id: string; platform: string; title: string; event: string; bid: number; ask: number }
export const strategyNames: Record<string, string> = { momentum: 'Momentum baseline', agent_filtered: 'Momentum + Agent filter', buy_hold: 'Buy and hold benchmark' }
export const paperReasons: Record<string, string> = {
  awaiting_orderbook: 'Awaiting order book', stale_orderbook: 'Order book is stale', stale_metadata: 'Market metadata is stale',
  market_not_open: 'Market is not open', missing_two_sided_quote: 'Two-sided quotes unavailable', unknown_fees: 'Fee parameters unavailable',
  spread_above_limit: 'Spread exceeds the experiment limit', rules_changed: 'Contract rules changed', stale_market_observation: 'Market observation is stale',
  hold_until_resolution: 'Holding until verified resolution', holding_period_elapsed: 'One-hour holding period reached', momentum_reversed: 'Momentum reversed',
  holding_position: 'Holding position', near_market_close: 'Market closes within one hour', reentry_cooldown: 'Re-entry cooldown',
  buy_hold_benchmark: 'Initial benchmark purchase', insufficient_price_history: 'Insufficient continuous price history', momentum_below_threshold: '15m movement below 2 pp',
  positive_15m_momentum: '15m movement reached 2 pp', awaiting_agent_report: 'Awaiting a recent Agent report', agent_risk_veto: 'Agent risk filter abstained',
  capital_or_event_limit: 'Capital or event exposure limit', no_eligible_fill_before_expiry: 'Order expired without an eligible fill',
  snapshot_ioc: 'Simulated against the next eligible book', insufficient_depth_or_price_limit: 'Insufficient depth or price outside limit',
  review_signal_changed: 'Entry signal is no longer eligible',
  review_pending: 'Review queued or running', review_model_unavailable: 'Waiting for model configuration',
  review_configuration_changed: 'Model settings or permissions changed', review_daily_limit: 'Daily review allowance reached',
  review_queue_busy: 'Waiting for the workspace model queue', review_cooldown: 'Review cooldown',
  review_expired: 'Review opportunity expired', review_price_changed: 'Price moved beyond the review limit',
  review_invalid: 'Review evidence is invalid', review_allowed: 'Review allowed a simulated entry',
  review_rejected: 'Review rejected the entry', review_abstained: 'Review is waiting for evidence', review_failed: 'Review failed or was cancelled',
  experiment_paused: 'Experiment paused', market_settled: 'Market settled',
}

export type PaperReview = {
  id: string; market_id: string; title: string; detected_at: string; expires_at: string
  state: string; reason: string; run_state: string | null; review_decision: string | null
  model: string | null; error_code: string; baseline_filled: boolean; agent_filled: boolean
}
export type ReviewClaim = { kind: string; text: string; references: string[] }
export type PaperReviewDetail = PaperReview & {
  inputs: Record<string, unknown>; context: Record<string, unknown> | null
  report: { decision: string; rationale: ReviewClaim; blocking_risks: ReviewClaim[]; cautions: ReviewClaim[]; missing_evidence: string[] } | null
  usage: Record<string, number>; finished_at: string | null
}
export type PaperReviewSummary = {
  model_ready: boolean; model: string; daily_limit: number; calls_today: number; calls_remaining: number
  candidates: number; reviewed: number; allowed: number; rejected: number; abstained: number
  invalidated: number; failed: number; waiting: number; paired_candidates: number; paired_agent_entries: number
  participation: number | null; provider_calls: number; prompt_tokens: number; completion_tokens: number
  average_latency_seconds: number | null; average_queue_seconds: number | null; model_cost_usd: string | null
}
