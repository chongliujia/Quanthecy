import { useSyncExternalStore } from 'react'

function subscribe(callback: () => void) {
  window.addEventListener('hashchange', callback)
  return () => window.removeEventListener('hashchange', callback)
}

export function useRoute() {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash || '#/overview')
  const [path, search = ''] = hash.slice(1).split('?')
  const segments = path.split('/').filter(Boolean)
  return { page: segments[0] || 'overview', id: segments[1], params: new URLSearchParams(search) }
}

export function navigate(path: string) { window.location.hash = path }
export function withCutoff(path: string, cutoff: string) { return cutoff ? `${path}?cutoff=${encodeURIComponent(cutoff)}` : path }
