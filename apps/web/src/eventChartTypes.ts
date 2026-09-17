import type { ResearchEvent } from './EventPages'

export type EventContract = { id: string; platform: string; title: string; outcome: string; resolution_rules: string; closes_at: string | null; linked_at: string }
export type EventChartPoint = { at: string; probability: number | null; observed_at: string | null; observation_id: string | null; issue: 'missing' | 'stale' | 'invalid_quote' | 'contract_changed' | null }
export type EventChartData = {
  event: ResearchEvent; start: string; end: string; step_seconds: number; max_age_seconds: number;
  contracts: EventContract[]; contracts_truncated: boolean;
  series: { market_id: string; points: EventChartPoint[]; truncated: boolean }[];
}
