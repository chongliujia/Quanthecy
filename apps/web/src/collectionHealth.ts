import { t } from './i18n'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type CollectionSource = {
  platform: string; state: 'recent' | 'delayed' | 'empty'; latest_observation: string | null;
  delay_seconds: number | null; total_markets: number; fresh_markets: number;
  collector_checked_at: string | null; error_code: string | null;
  run_state?: 'active' | 'paused' | 'pause_pending' | 'configuration_pending' | 'request_failed' | 'no_heartbeat' | 'delayed' | 'unknown';
  managed?: boolean; enabled_targets?: number | null; desired_revision?: number | null; applied_revision?: number | null;
}
export type CollectionHealth = { checked_at: string; sources: CollectionSource[]; analytics_state?: 'active' | 'no_heartbeat' | 'unavailable'; analytics_checked_at?: string | null }
export const collectionLabels: Record<string, string> = {
  active: 'Collecting', paused: 'Paused by configuration', pause_pending: 'Pause pending',
  configuration_pending: 'Configuration pending', request_failed: 'Request failed',
  no_heartbeat: 'No collector heartbeat', delayed: 'Delayed', unknown: 'Diagnostics unavailable',
}
export const collectionExplanations: Record<string, string> = {
  paused: 'The collector acknowledged an empty collection plan for this exchange. Saved history remains available.',
  pause_pending: 'This exchange has no enabled targets. The collector has not acknowledged this pause yet.',
  configuration_pending: 'The requested collection plan has not been acknowledged. The collector may still use its previous plan.',
  no_heartbeat: 'No recent collection heartbeat is available. The service may be stopped, delayed, or disconnected. Saved quotes do not prove it is running.',
  unknown: 'Collector diagnostics are unavailable. Inspect observation freshness separately.',
  delayed: 'The collector has reported recently, but saved market observations are delayed.',
}
export function age(seconds: number | null) {
  if (seconds == null) return t('No observations')
  if (seconds < 60) return t('{seconds}s ago', { seconds })
  if (seconds < 3600) return t('{minutes}m ago', { minutes: Math.floor(seconds / 60) })
  return t('{hours}h {minutes}m ago', { hours: Math.floor(seconds / 3600), minutes: Math.floor(seconds % 3600 / 60) })
}
export function useCollectionStatus(userId: string) {
  return useQuery({ queryKey: ['collection-status', userId], queryFn: () => api<CollectionHealth>('/collection/status'), refetchInterval: 30000 })
}
