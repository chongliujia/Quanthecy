import { expect, it } from 'vitest'
import { chartData } from './chartData'
import type { Observation } from './marketTypes'

function row(minute: number, volume: number, changes: Partial<Observation> = {}): Observation {
  return { observation_id: String(minute), received_at: new Date(Date.UTC(2026, 0, 1, 0, minute)).toISOString(), probability: { value: 0, basis: 'MIDPOINT', source: 'test' }, best_bid: 0, best_ask: 0.02, volume: { value: volume, unit: 'USD', basis: 'CUMULATIVE' }, quality_flags: [], market: { resolution_rules: 'Example', rules_version: '1', closes_at: null }, ...changes }
}
it('preserves zero probabilities and shows only compatible sampled volume changes', () => {
  const result = chartData([row(0, 10), row(1, 25), row(2, 2), row(3, 50, { volume: { value: 50, unit: 'USD', basis: 'ROLLING_24H' } })])
  expect(result.probability.map((point) => point[1])).toEqual([0, 0, 0, 0])
  expect(result.volume.map((point) => point[1])).toEqual([null, 15, null, null])
})
it('leaves sampling gaps open and never invents volume across missing intervals', () => {
  const result = chartData([row(0, 10), row(5, 100)])
  expect(result.probability.map((point) => point[1])).toEqual([0, null, 0])
  expect(result.volume.map((point) => point[1])).toEqual([null, null])
  expect(result.bid.map((point) => point[1])).toEqual([0, null, 0])
  expect(result.ask.map((point) => point[1])).toEqual([2, null, 2])
})
it('never paints a quote band for missing, crossed, stale or out-of-range quotes', () => {
  const result = chartData([row(0, 0), row(1, 0, { best_bid: null }), row(2, 0, { best_bid: .9, best_ask: .8 }), row(3, 0, { best_ask: 1.1 }), row(4, 0, { quality_flags: ['STALE'] })])
  expect(result.bid.map((point) => point[1])).toEqual([0, null, null, null, null])
  expect(result.band.map((point) => point[1])).toEqual([2, null, null, null, null])
})
it('does not combine different volume units or chart an invalid crossed spread', () => {
  const result = chartData([row(0, 10), row(1, 20, { volume: { value: 20, unit: 'CONTRACTS', basis: 'CUMULATIVE' }, best_bid: 0.6, best_ask: 0.5 })])
  expect(result.volumeUnit).toBeNull()
  expect(result.volume.map((point) => point[1])).toEqual([null, null])
  expect(result.spread[1][1]).toBeNull()
})

it('keeps a readable bounded probability axis at zero, one hundred and flat prices', async () => {
  const { probabilityBounds, chartNumber } = await import('./chartData')
  for (const price of [0, 0.15, 79.49999999999999, 100]) {
    const bounds = probabilityBounds([null, price, price])
    expect(bounds.min).toBeLessThanOrEqual(price)
    expect(bounds.max).toBeGreaterThanOrEqual(price)
    expect(bounds.min).toBeGreaterThanOrEqual(0)
    expect(bounds.max).toBeLessThanOrEqual(100)
    expect(bounds.max).toBeGreaterThan(bounds.min)
  }
  expect(chartNumber(79.49999999999999, '%')).toBe('79.5%')
  expect(chartNumber(null, '%')).toBe('—')
  expect(chartNumber(0, '%')).toBe('0%')
})
it('groups crowded events without losing events or mixing five-minute boundaries', async () => {
  const { eventBuckets } = await import('./chartData')
  const items = [row(5, 0), row(1, 0), row(0, 0), row(4, 0)]
  const grouped = eventBuckets(items, (item) => item.received_at)
  expect(grouped.map((group) => group.map((item) => item.observation_id))).toEqual([['0', '1', '4'], ['5']])
  expect(items[0].observation_id).toBe('5')
})
