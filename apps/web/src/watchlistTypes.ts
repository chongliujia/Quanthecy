import type { Market } from './marketTypes'

export type Watchlist = { id: string; name: string; count: number }
export type WatchlistDetail = Watchlist & { items: { market: Market; position: number }[] }
export type AlertRuleInput = {
  name: string; kind: 'PROBABILITY_MOVE' | 'SPREAD_WIDENING'; direction: 'EITHER' | 'UP' | 'DOWN';
  threshold_pp: string | number; window_minutes: number; cooldown_minutes: number; enabled: boolean
}
export type AlertRule = AlertRuleInput & {
  id: string; watchlist_id: string; revision: number;
  states: { market_id: string; title: string; status: string; reason: string; value_pp: number | null; evaluated_at: string | null }[]
}
export type AlertEvent = {
  id: string; market_id: string; title: string; platform: string; rule_name: string;
  kind: AlertRuleInput['kind']; direction: AlertRuleInput['direction']; threshold_pp: number;
  window_minutes: number; value_pp: number; revision: number; observed_at: string; created_at: string; is_read: boolean
}
export type AlertPage = { items: AlertEvent[]; total: number; unread: number; offset: number; limit: number }
export type AlertDetail = AlertEvent & { snapshot: {
  watchlist_name: string; rule: AlertRuleInput; calculation: {
    version: string; window_start: string; window_end: string; max_gap_seconds: number; minimum_samples: number;
    inputs: { observation_id: string; received_at: string; recorded_at: string; best_bid: number; best_ask: number; probability: { value: number; basis: string }; rules_version: string; quality_flags: string[] }[]
  }
} }

export const directionLabels: Record<string, string> = { EITHER: 'Either direction', UP: 'Increase', DOWN: 'Decrease' }
