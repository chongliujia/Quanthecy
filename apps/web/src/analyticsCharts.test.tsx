import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import MarketHeatmap from './MarketHeatmap'
import EventProbabilityChart from './EventProbabilityChart'
import EventComparison from './EventComparison'
import { heatmapValue } from './heatmapData'
import { setThemePreference } from './theme'
import type { Market } from './marketTypes'
import type { EventChartData } from './eventChartTypes'

const canvas = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }))
vi.mock('echarts/core', () => ({ init: () => canvas, use: vi.fn() }))
vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
beforeEach(() => vi.clearAllMocks())
const market: Market = { id: 'm1', platform: 'kalshi', exchange_id: 'x', title: 'First contract', status: 'OPEN', probability: .5, best_bid: .49, best_ask: .51, stale: false, first_observed_at: new Date().toISOString(), last_observed_at: new Date().toISOString(), quality_flags: [], metrics: { version: 'v', history_ready: true, reason: null, probability_change_15m: .01, spread_change_15m: 0, volume_zscore: null }, data_quality: { version: 'v', checked_at: new Date().toISOString(), state: 'limited', price_usable: true, volume_usable: false, reasons: [], limitations: [], age_seconds: 0 } }
function mount(children: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>) }

it('colors only fresh qualified changes, retains zero, and caps intensity without capping the number', () => {
  const now = Date.now()
  expect(heatmapValue(market, now).value).toBe(.01)
  expect(heatmapValue(market, now).intensity).toBeCloseTo(.2)
  expect(heatmapValue({ ...market, metrics: { ...market.metrics, probability_change_15m: 0 } }, now).value).toBe(0)
  expect(heatmapValue({ ...market, metrics: { ...market.metrics, probability_change_15m: -.25 } }, now)).toMatchObject({ value: -.25, intensity: 1 })
  expect(heatmapValue(market, now + 181000)).toMatchObject({ value: null, state: 'stale' })
  expect(heatmapValue({ ...market, data_quality: undefined }, now).value).toBeNull()
  expect(heatmapValue({ ...market, status: 'CLOSED' }, now).value).toBeNull()
  expect(heatmapValue({ ...market, last_observed_at: new Date(now + 5000).toISOString() }, now).value).toBeNull()
})

it('scopes heatmap requests to the workspace and opens the actual clicked market', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => new Response(JSON.stringify(String(input).endsWith('/watchlists') ? [{ id: 'list1', name: 'My research', count: 1 }] : { items: [market], total: 1 })))
  const select = vi.fn()
  mount(<MarketHeatmap userId="u" organization={{ id: 'org1', name: 'Workspace', role: 'OWNER', slug: 'org1', kind: 'TEAM' }} watchlist="list1" onWatchlistChange={vi.fn()} onSelect={select} />)
  fireEvent.click(await screen.findByRole('button', { name: /First contract/ }))
  expect(select).toHaveBeenCalledWith('m1')
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('&watchlist_id=list1&organization_id=org1'), expect.anything())
  expect(fetch.mock.calls.filter(([url]) => String(url).includes('/markets?')).every(([url]) => !String(url).includes('&platform='))).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Polymarket' }))
  await screen.findByRole('button', { name: /First contract/ })
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('&platform=polymarket'), expect.anything())
})

const data: EventChartData = { event: { id: 'event', slug: 'fed', version: 1, title: 'Fed', title_zh: '', scope: 'Related', scope_zh: '', starts_on: '', ends_on: '', calendar_url: '', observed_at: '', market_count: 7 }, start: '2026-01-01T12:00:00Z', end: '2026-01-01T13:00:00Z', step_seconds: 60, max_age_seconds: 90, contracts_truncated: false,
  contracts: Array.from({ length: 7 }, (_, i) => ({ id: `m${i}`, platform: 'kalshi', title: `Contract ${i}`, outcome: 'Yes', resolution_rules: 'Rules', closes_at: null, linked_at: '' })),
  series: Array.from({ length: 6 }, (_, i) => ({ market_id: `m${i}`, truncated: false, points: [{ at: '2026-01-01T12:00:00Z', probability: .7, observed_at: '2026-01-01T11:59:50Z', observation_id: 'x', issue: null }, { at: '2026-01-01T13:00:00Z', probability: i ? null : .8, observed_at: null, observation_id: null, issue: i ? 'stale' : null }] })) }

it('keeps independent probabilities, missing bars, selection limits and theme updates', () => {
  setThemePreference('dark')
  const selected = data.series.map((line) => line.market_id)
  const selection = vi.fn()
  const view = render(<EventProbabilityChart data={data} view="history" selected={selected} onSelection={selection} />)
  const history = canvas.setOption.mock.lastCall![0]
  expect(history.series[0].data[0].value[1]).toBe(70)
  expect(history.series[1].data[1].value[1]).toBeNull()
  expect(history.series[0].connectNulls).toBe(false)
  expect(screen.getAllByRole('checkbox')[6]).toBeDisabled()
  fireEvent.click(screen.getAllByRole('checkbox')[0])
  expect(selection).toHaveBeenCalledWith(selected.slice(1))
  view.rerender(<EventProbabilityChart data={data} view="latest" selected={selected} onSelection={selection} />)
  expect(canvas.setOption.mock.lastCall![0].series[0].data.map((item: { value: number | null }) => item.value)).toEqual([80, null, null, null, null, null])
  act(() => setThemePreference('light'))
  expect(canvas.setOption.mock.lastCall![0].tooltip.backgroundColor).toBe('#ffffff')
  expect(canvas.dispose).not.toHaveBeenCalled()
})

it('explains an unlinked event without making arbitrary cross-contract comparisons', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]'))
  mount(<EventComparison userId="u" marketId="m1" platform="kalshi" cutoff="" />)
  expect(await screen.findByText('No linked research event')).toBeVisible()
  expect(fetch).toHaveBeenCalledTimes(1)
})
