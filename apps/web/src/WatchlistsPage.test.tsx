import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { Organization } from './api'
import WatchlistsPage from './WatchlistsPage'
import { WatchMarketButton } from './WatchlistControls'
import AlertInbox from './AlertInbox'
import MarketExplorer from './MarketExplorer'
import { setLanguage } from './i18n'

const organization: Organization = { id: 'org1', name: 'Research', slug: 'research', kind: 'TEAM', role: 'OWNER' }
const list = { id: 'list1', name: 'Rates', count: 0 }
function respond(body: unknown) { return new Response(JSON.stringify(body)) }
function mockApi() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    if (path.endsWith('/auth/csrf')) return respond({ csrf_token: 'test' })
    if (path.endsWith('/collection/status')) return respond({ sources: [], analytics_state: 'no_heartbeat' })
    if (path.endsWith('/watchlists')) return respond([list])
    if (path.endsWith('/rules') || path.endsWith('/research/topics')) return respond([])
    if (path.includes('/markets?')) return respond({ items: [], total: 0 })
    return respond({ ...list, items: [] })
  })
}
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

it('requires a workspace before making watchlist requests', () => {
  const fetch = mockApi()
  render(<WatchlistsPage userId="u1" />, { wrapper: wrapper() })
  expect(screen.getByText('Select a workspace to manage watchlists.')).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})

it('keeps viewer lists read only and explains missing processing heartbeat', async () => {
  mockApi()
  render(<WatchlistsPage userId="u1" organization={{ ...organization, role: 'VIEWER' }} />, { wrapper: wrapper() })
  await screen.findByText('This watchlist is empty. Add collected markets from the research terminal.')
  expect(screen.queryByRole('button', { name: 'Create watchlist' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '+ Rule' })).not.toBeInTheDocument()
  expect(screen.getByText(/A stopped or delayed worker/)).toBeVisible()
})

it('submits localized direction choices using canonical rule values and workspace scope', async () => {
  const fetch = mockApi()
  setLanguage('zh')
  render(<WatchlistsPage userId="u1" organization={organization} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: '+ 新建规则' }))
  fireEvent.change(screen.getByLabelText('规则名称'), { target: { value: '跌幅提醒' } })
  fireEvent.change(screen.getByLabelText('方向'), { target: { value: 'DOWN' } })
  fireEvent.change(screen.getByLabelText('阈值（百分点）'), { target: { value: '2.5' } })
  fireEvent.click(screen.getByRole('button', { name: '保存规则' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/watchlists/list1/rules', expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: '跌幅提醒', kind: 'PROBABILITY_MOVE', direction: 'DOWN', threshold_pp: '2.5', window_minutes: 15, cooldown_minutes: 30, enabled: true }) })))
})

it('replaces cached watchlist content when switching workspaces', async () => {
  const fetch = mockApi()
  const view = render(<WatchlistsPage userId="u1" organization={organization} />, { wrapper: wrapper() })
  await screen.findByRole('heading', { name: 'Rates' })
  fetch.mockImplementation(async input => String(input).endsWith('/collection/status') ? respond({ sources: [], analytics_state: 'active' }) : respond([]))
  view.rerender(<WatchlistsPage userId="u1" organization={{ ...organization, id: 'org2' }} />)
  await screen.findByText('Start with the markets you follow')
  expect(screen.queryByRole('heading', { name: 'Rates' })).not.toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org2/watchlists', expect.anything())
})

it('adds a market through the workspace list without changing collection settings', async () => {
  const fetch = mockApi()
  render(<WatchMarketButton userId="u1" organization={organization} marketId="m1" />, { wrapper: wrapper() })
  fireEvent.click(screen.getByRole('button', { name: '☆ Watch market' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Add market' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/watchlists/list1/items', expect.objectContaining({ method: 'POST', body: '{"market_id":"m1"}' })))
  expect(fetch.mock.calls.some(([path]) => String(path).includes('/selection'))).toBe(false)
})

it('filters the market scanner with both workspace and watchlist identifiers', async () => {
  const fetch = mockApi()
  render(<MarketExplorer userId="u1" organization={organization} watchlistId="list1" />, { wrapper: wrapper() })
  await screen.findByRole('option', { name: 'Rates' })
  await waitFor(() => expect(fetch.mock.calls.some(([path]) => String(path).includes('watchlist_id=list1') && String(path).includes('organization_id=org1'))).toBe(true))
})

it('shows frozen trigger quotes and updates only the current user read receipt', async () => {
  const event = { id: 'a1', market_id: 'm1', title: 'Rate decision', platform: 'kalshi', rule_name: 'Movement', kind: 'PROBABILITY_MOVE', direction: 'UP', threshold_pp: 3, window_minutes: 15, value_pp: 5, revision: 2, observed_at: '2026-09-17T00:00:00Z', is_read: false }
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const path = String(input)
    if (path.endsWith('/auth/csrf')) return respond({ csrf_token: 'test' })
    if (path.endsWith('/read')) return respond({ detail: 'Saved' })
    if (path.endsWith('/a1')) return respond({ ...event, snapshot: { calculation: { version: 'watchlist-window-v1', window_start: '2026-09-16T23:45:00Z', window_end: event.observed_at, inputs: [{ observation_id: 'o1', received_at: event.observed_at, recorded_at: '2026-09-17T00:00:00.435Z', probability: { value: .45 }, best_bid: .44, best_ask: .46 }] } } })
    return respond({ items: [event], total: 1, unread: 1 })
  })
  render(<AlertInbox userId="u1" organizationId="org1" />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: 'Trigger details' }))
  const link = await screen.findByRole('link', { name: 'Open market at trigger time →' })
  expect(link).toHaveAttribute('href', '#/markets/m1?cutoff=2026-09-17T00%3A00%3A00.435Z')
  expect(screen.getByText('45.00%')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Close Alert trigger details' }))
  fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/alerts/a1/read', expect.objectContaining({ method: 'PATCH', body: '{"read":true}' })))
})
