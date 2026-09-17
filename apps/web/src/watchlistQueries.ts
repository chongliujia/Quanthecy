import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Watchlist, WatchlistDetail } from './watchlistTypes'

export function useWatchlists(userId: string, organizationId?: string) {
  return useQuery({ queryKey: ['watchlists', userId, organizationId], enabled: !!organizationId,
    queryFn: () => api<Watchlist[]>(`/organizations/${organizationId}/watchlists`) })
}

export function useWatchlist(userId: string, organizationId?: string, listId?: string) {
  return useQuery({ queryKey: ['watchlist', userId, organizationId, listId], enabled: !!organizationId && !!listId,
    queryFn: () => api<WatchlistDetail>(`/organizations/${organizationId}/watchlists/${listId}`), refetchInterval: 30000 })
}
