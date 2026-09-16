import { t } from './i18n'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type CollectionSource = {
  platform: string; state: 'recent' | 'delayed' | 'empty'; latest_observation: string | null;
  delay_seconds: number | null; total_markets: number; fresh_markets: number;
  collector_checked_at: string | null; error_code: string | null;
}
export type CollectionHealth = { checked_at: string; sources: CollectionSource[] }
export function age(seconds: number | null) {
  if (seconds == null) return t('No observations')
  if (seconds < 60) return t('{seconds}s ago', { seconds })
  if (seconds < 3600) return t('{minutes}m ago', { minutes: Math.floor(seconds / 60) })
  return t('{hours}h {minutes}m ago', { hours: Math.floor(seconds / 3600), minutes: Math.floor(seconds % 3600 / 60) })
}
export function useCollectionStatus(userId: string) {
  return useQuery({ queryKey: ['collection-status', userId], queryFn: () => api<CollectionHealth>('/collection/status'), refetchInterval: 30000 })
}
