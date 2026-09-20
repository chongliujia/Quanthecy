import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ResearchOverview } from './ResearchPages'

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ResearchOverview userId="u1" /></QueryClientProvider>)
}
function respondMovers(movers: () => Response) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const path = String(input)
    if (path.includes('/markets?')) return movers()
    const body = path.endsWith('/comparisons') ? [] : path.includes('/evidence?') ? { items: [], total: 0 }
      : { markets: 12, fresh_markets: 0, reviewed_pairs: 0, evidence_items: 0, sources: [], latest_observation: null, news_polling_enabled: true }
    return new Response(JSON.stringify(body))
  })
}
it('keeps an empty ranking explicit instead of generating movements from the coverage count', async () => {
  respondMovers(() => new Response(JSON.stringify({ items: [], total: 0 })))
  mount()
  expect(await screen.findByText('No qualifying movement yet')).toBeVisible()
  expect(screen.getByText('12')).toBeVisible()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})
it('uses the API ranking, preserves unavailable prices, and links to market research', async () => {
  const fetch = respondMovers(() => new Response(JSON.stringify({ items: [
    { id: 'm1', title: 'A selected contract', platform: 'kalshi', probability: null, last_observed_at: '2026-09-20T00:00:00Z', metrics: { probability_change_15m: -.031 } },
  ], total: 1 })))
  mount()
  expect(await screen.findByRole('link', { name: 'A selected contract' })).toHaveAttribute('href', '#/markets/m1')
  expect(screen.getByText('Unavailable')).toBeVisible()
  expect(screen.getByText('-3.10 pp')).toBeVisible()
  expect(fetch).toHaveBeenCalledWith('/api/v1/markets?limit=6&sort=movement', expect.anything())
})
it('recovers from a ranking error without discarding the coverage summary', async () => {
  let failed = true
  respondMovers(() => failed ? new Response(JSON.stringify({ detail: 'Market ranking unavailable' }), { status: 503 }) : new Response(JSON.stringify({ items: [], total: 0 })))
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('Market ranking unavailable')
  expect(screen.getByText('12')).toBeVisible()
  failed = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(await screen.findByText('No qualifying movement yet')).toBeVisible()
})
