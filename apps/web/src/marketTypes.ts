export type Metrics = {
  version: string; history_ready: boolean; reason: string | null;
  probability_change_15m: number | null; spread_change_15m: number | null;
  volume_zscore: number | null; window_end?: string | null;
}
export type Market = {
  id: string; platform: string; exchange_id: string; title: string; status: string;
  probability: number | null; best_bid: number | null; best_ask: number | null;
  first_observed_at: string; last_observed_at: string; stale: boolean;
  quality_flags: string[]; metrics: Metrics;
}
export type Observation = {
  observation_id: string; received_at: string; quality_flags: string[];
  best_bid: number | null; best_ask: number | null;
  probability: { value: number; basis: string; source: string } | null;
  volume: { value: number; unit: string; basis: string } | null;
  recorded_at?: string;
  market: { resolution_rules: string; rules_version: string; closes_at: string | null };
}
export type MarketDetail = Market & { latest: Observation; live_cache: boolean }
export type History = { items: Observation[]; truncated: boolean; start: string; end: string }
export type Signal = {
  id: string; signal_type: string; received_at: string; version: string;
  metrics: Metrics; observation_ids: string[];
}
