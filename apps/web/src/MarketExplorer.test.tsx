import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import MarketExplorer from './MarketExplorer'

beforeEach(() => localStorage.clear())
afterEach(() => localStorage.clear())

vi.mock('./ProbabilityChart', () => ({ default: () => <div>Probability chart</div> }))

const market = { id: 'm1', platform: 'kalshi', title: 'A research question?', exchange_id: 'TICKER', status: 'OPEN',
  probability: null, best_bid: null, best_ask: null, first_observed_at: '2026-01-01T12:00:00Z',
  last_observed_at: '2026-01-01T12:15:00Z', stale: true, quality_flags: ['PARTIAL'],
  metrics: { version: 'rest-window-v1', history_ready: false, reason: 'insufficient_history', probability_change_15m: null, spread_change_15m: null, volume_zscore: null },
}

function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MarketExplorer userId="u1" /></QueryClientProvider>)
}

it('explains bounded coverage and empty history while sampling warms up', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => new Response(JSON.stringify(String(input).endsWith('/research/topics') ? [] : { items: [], total: 0 })))
  mount()
  expect(await screen.findByText('No markets to show yet')).toBeInTheDocument()
  expect(screen.getByText(/Coverage: selected binary markets/)).toBeInTheDocument()
})

it('shows a recoverable market API error', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Market history unavailable'))
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('Market history unavailable')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

it('preserves unknown probabilities and stale status through detail navigation', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    if (path.endsWith('/research/topics')) return new Response('[]')
    const body = path.includes('/history?') ? { items: [], truncated: false, start: '2026-01-01T00:00:00Z', end: '2026-01-02T00:00:00Z' }
      : path.endsWith('/timeline') ? { items: [], truncated: false } : path.endsWith('/signals') || path.endsWith('/comparisons') ? [] : path.endsWith('/m1') ? { ...market, live_cache: false,
        latest: { market: { resolution_rules: 'Settlement terms', rules_version: 'v1' }, volume: null } }
        : { items: [market], total: 1 }
    return new Response(JSON.stringify(body))
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  // The first navigation also loads the terminal's lazy module on a cold build.
  expect(await screen.findByText(/Collection is stale/, {}, { timeout: 5000 })).toBeInTheDocument()
  expect(screen.getByText(/Analytics pending: insufficient history/)).toBeInTheDocument()
  expect(await screen.findByText(/No observations in this window/)).toBeInTheDocument()
  expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '← All markets' }))
  expect(await screen.findByRole('heading', { name: 'Market explorer' })).toBeInTheDocument()
})

it('scopes platform filtering and movement ranking to backend query parameters', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => new Response(JSON.stringify(String(input).endsWith('/research/topics') ? [] : { items: [], total: 0 })))
  mount()
  await screen.findByText('No markets to show yet')
  fireEvent.change(screen.getByLabelText('Platform'), { target: { value: 'kalshi' } })
  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'movement' } })
  await screen.findByText('0 markets with fresh, comparable metrics')
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('sort=movement&search=&platform=kalshi'), expect.anything())
})

it('links a selected signal to evidence available at its timestamp and exposes the contract', async () => {
  const signal = { id: 's1', signal_type: 'PROBABILITY_SPIKE', received_at: new Date(Date.now() - 60000).toISOString(), version: 'v1', metrics: { probability_change_15m: 0.06, spread_change_15m: 0.01, volume_zscore: 3 }, observation_ids: ['input-1'] }
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    if (path.endsWith('/research/topics')) return new Response('[]')
    const body = path.includes('/history?') ? { items: [], truncated: false, start: new Date(Date.now() - 86400000).toISOString(), end: new Date().toISOString() }
      : path.includes('/timeline') ? { items: [], truncated: false }
        : path.endsWith('/signals') ? [signal]
          : path.endsWith('/comparisons') ? []
            : path.endsWith('/m1') ? { ...market, latest: { market: { resolution_rules: 'Inspect settlement wording', rules_version: 'v1' }, volume: null } }
              : { items: [market], total: 1 }
    return new Response(JSON.stringify(body))
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  fireEvent.click(await screen.findByRole('tab', { name: /Signals/ }))
  fireEvent.click(await screen.findByRole('button', { name: /probability spike/i }))
  expect(await screen.findByText('Signal inspection')).toBeInTheDocument()
  await screen.findByText('No associated evidence available at this cutoff.')
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining(`/timeline?cutoff=${encodeURIComponent(signal.received_at)}`), expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'Contract' }))
  expect(screen.getByText('Inspect settlement wording')).toBeInTheDocument()
})

it('opens saved history using recording time and keeps unavailable metrics neutral', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    if (path.endsWith('/research/topics')) return new Response('[]')
    const body = path.includes('/history?') ? { items: [], truncated: false, start: '2026-01-01T00:00:00Z', end: '2026-01-02T00:00:00Z' }
      : path.includes('/timeline') ? { items: [] } : path.endsWith('/signals') || path.endsWith('/comparisons') ? []
        : path.endsWith('/m1') ? { ...market, latest: { recorded_at: '2026-01-01T12:15:08Z', market: {}, volume: null } }
          : { items: [market], total: 1 }
    return new Response(JSON.stringify(body))
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  const links = await screen.findAllByRole('link', { name: 'View last collected window →' })
  expect(links[0]).toHaveAttribute('href', '#/markets/m1?cutoff=2026-01-01T12%3A15%3A08.000Z')
  expect(document.querySelector('.quote-strip .positive')).toBeNull()
})


it('filters by a research topic and reports gaps without implying full coverage', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    const body = path.endsWith('/research/topics') ? [{ slug: 'fed-october', name: 'October Fed', name_zh: '十月议息', description: 'October FOMC scope', description_zh: '十月研究范围', configured: 10, observed: 8, fresh: 7, price_usable: 4, volume_usable: 2, missing: 2, needs_attention: 3 }]
      : path.includes('/markets?') ? { items: [market], total: 1 } : { sources: [] }
    return new Response(JSON.stringify(body))
  })
  mount()
  await screen.findByRole('option', { name: 'October Fed' })
  fireEvent.change(screen.getByLabelText('Research topic'), { target: { value: 'fed-october' } })
  expect(await screen.findByRole('region', { name: 'Topic coverage' })).toHaveTextContent('Awaiting first observation: 2. Targets needing attention: 3.')
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('&topic=fed-october'), expect.anything())
  expect(screen.getByText('A shared topic does not establish equivalent settlement rules or an arbitrage opportunity.')).toBeInTheDocument()
})

function mockTerminal() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    const body = path.endsWith('/watchlists') ? [{ id: 'list1', name: 'Rates', count: 1 }] : path.endsWith('/research/topics') || path.endsWith('/signals') || path.endsWith('/comparisons') ? []
      : path.includes('/history?') ? { items: [], truncated: false, start: '2026-01-01T00:00:00Z', end: '2026-01-02T00:00:00Z' }
        : path.includes('/timeline') ? { items: [], truncated: false }
          : path.endsWith('/m1') ? { ...market, latest: { market: { resolution_rules: 'Inspect settlement wording', rules_version: 'v1' }, volume: null } }
            : { items: [market], total: 1 }
    return new Response(JSON.stringify(body))
  })
}

it('keeps desktop research beside the chart and restores a hidden side panel', async () => {
  const fetch = mockTerminal()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  await screen.findByText('No observations in this window')
  fireEvent.click(screen.getByRole('button', { name: 'Research' }))
  expect(screen.getByRole('region', { name: 'Research inspector' })).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Contract' }))
  expect(screen.getByText('Inspect settlement wording')).toBeVisible()
  expect(screen.getByText('No observations in this window')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Hide side panel' }))
  expect(screen.queryByRole('region', { name: 'Research inspector' })).not.toBeInTheDocument()
  expect(localStorage.getItem('quanthecy.sidebar.u1')).toBe('false')
  fireEvent.click(screen.getByRole('button', { name: 'Research & agent' }))
  expect(screen.getByText('Inspect settlement wording')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '✧ Agent' }))
  expect(screen.getByRole('dialog', { name: 'Research inspector' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Close Research inspector' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByText('Market overview')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Markets' }))
  expect(screen.getByLabelText('Filter market sidebar')).toBeVisible()
  expect(fetch.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)
})

it('supports keyboard panel resizing and keeps the activity panel collapsible', async () => {
  mockTerminal()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  const side = await screen.findByRole('separator', { name: 'Side panel width' })
  fireEvent.keyDown(side, { key: 'ArrowLeft' })
  expect(side).toHaveAttribute('aria-valuenow', '320')
  expect(localStorage.getItem('quanthecy.sidebar-width.u1')).toBe('320')
  expect(screen.queryByRole('separator', { name: 'Activity panel height' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: /News & evidence/ }))
  const activity = screen.getByRole('separator', { name: 'Activity panel height' })
  fireEvent.keyDown(activity, { key: 'ArrowUp' })
  expect(activity).toHaveAttribute('aria-valuenow', '196')
  expect(screen.getByRole('tabpanel', { name: /News & evidence/ })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Collapse activity' }))
  expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
  expect(screen.queryByRole('separator', { name: 'Activity panel height' })).not.toBeInTheDocument()
})

it('uses a closable research dialog on compact screens', async () => {
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({ matches: query === '(max-width: 1100px)', media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true }))
  mockTerminal()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  await screen.findByText('No observations in this window')
  expect(screen.queryByRole('separator', { name: 'Side panel width' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Research & agent' }))
  expect(screen.getByRole('dialog', { name: 'Research inspector' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Close Research inspector' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})


it('preserves the selected watchlist between the scanner and market terminal', async () => {
  const fetch = mockTerminal()
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MarketExplorer userId="u1" watchlistId="list1" organization={{ id: 'org1', name: 'Research', slug: 'research', kind: 'TEAM', role: 'OWNER' }} /></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'A research question?' }))
  expect(await screen.findByLabelText('Watchlist')).toHaveValue('list1')
  expect(fetch.mock.calls.some(([path]) => String(path).includes('/markets?limit=40') && String(path).includes('watchlist_id=list1&organization_id=org1'))).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '← All markets' }))
  expect(await screen.findByLabelText('Watchlist')).toHaveValue('list1')
})
