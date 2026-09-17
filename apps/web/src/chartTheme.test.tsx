import { act, render } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import ProbabilityChart from './ProbabilityChart'
import ComparisonChart from './ComparisonChart'
import { setThemePreference } from './theme'
import type { ChartViewport } from './ProbabilityChart'
import type { Observation } from './marketTypes'

const chart = vi.hoisted(() => ({
  setOption: vi.fn(), dispose: vi.fn(), resize: vi.fn(), on: vi.fn(),
  getZr: () => ({ on: vi.fn() }), dispatchAction: vi.fn(),
}))
vi.mock('echarts/core', () => ({ init: vi.fn(() => chart), use: vi.fn() }))
vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
beforeEach(() => vi.clearAllMocks())

it('recolors the probability chart without replacing it or clearing its viewport', () => {
  setThemePreference('dark')
  const viewport = { current: { start: 25, end: 75 } as ChartViewport }
  const mounted = render(<ProbabilityChart rows={[]} viewport={viewport} />)
  const dark = chart.setOption.mock.lastCall?.[0]
  act(() => setThemePreference('light'))
  const light = chart.setOption.mock.lastCall?.[0]
  expect(light.yAxis[0].axisLabel.color).not.toBe(dark.yAxis[0].axisLabel.color)
  expect(light.series[0].lineStyle.color).not.toBe(dark.series[0].lineStyle.color)
  expect(light.dataZoom[0]).toMatchObject({ start: 25, end: 75 })
  expect(chart.dispose).not.toHaveBeenCalled()
  mounted.unmount()
})

it('updates comparison chart labels and tooltip colors on theme changes', () => {
  setThemePreference('dark')
  render(<ComparisonChart points={[]} left="Left market" right="Right market" />)
  const dark = chart.setOption.mock.lastCall?.[0]
  act(() => setThemePreference('light'))
  const light = chart.setOption.mock.lastCall?.[0]
  expect(light.tooltip.backgroundColor).toBe('#ffffff')
  expect(light.legend.textStyle.color).not.toBe(dark.legend.textStyle.color)
  expect(chart.dispose).not.toHaveBeenCalled()
  expect(light.series.map((series: { name: string }) => series.name)).toEqual(['Left market', 'Right market'])
})

it('includes both quote boundaries in auto scale and preserves zoom when toggled', () => {
  const rows: Observation[] = [{ observation_id: 'quote', received_at: '2026-01-01T00:00:00Z', probability: { value: .5, basis: 'MIDPOINT', source: 'fixture' }, best_bid: .4, best_ask: .6, volume: null, quality_flags: [], market: { resolution_rules: 'Rules', rules_version: 'v1', closes_at: null } }]
  const viewport = { current: { start: 20, end: 80 } as ChartViewport }
  const mounted = render(<ProbabilityChart rows={rows} autoScale quoteBand viewport={viewport} />)
  const band = chart.setOption.mock.lastCall![0]
  expect(band.yAxis[0].min).toBeLessThan(40)
  expect(band.yAxis[0].max).toBeGreaterThan(60)
  expect(band.series.find((item: { name: string }) => item.name === 'Quote baseline').data[0][1]).toBe(40)
  expect(band.series.find((item: { name: string }) => item.name === 'Quote range').data[0][1]).toBeCloseTo(20)
  mounted.rerender(<ProbabilityChart rows={rows} autoScale quoteBand={false} viewport={viewport} />)
  expect(chart.setOption.mock.lastCall![0].yAxis[0].min).toBeGreaterThan(40)
  expect(chart.setOption.mock.lastCall![0].dataZoom[0]).toMatchObject({ start: 20, end: 80 })
  expect(chart.dispose).not.toHaveBeenCalled()
})

it('adapts short charts and restores indicators without losing zoom', () => {
  let resize: (() => void) | undefined
  vi.stubGlobal('ResizeObserver', class { constructor(callback: () => void) { resize = callback } observe() {} disconnect() {} })
  const viewport = { current: { start: 20, end: 80 } as ChartViewport }
  const mounted = render(<ProbabilityChart rows={[]} viewport={viewport} />)
  const canvas = mounted.container.querySelector('.terminal-chart')!
  Object.defineProperty(canvas, 'clientHeight', { configurable: true, value: 180 })
  act(() => resize?.())
  const small = chart.setOption.mock.lastCall?.[0]
  expect(small.yAxis.map((axis: { show?: boolean }) => axis.show)).toEqual([undefined, false, false])
  expect(small.xAxis[0].axisLabel.show).toBe(true)
  expect(small.dataZoom[0]).toMatchObject({ start: 20, end: 80 })
  expect(mounted.getByTitle('Expand chart for volume & spread panes')).toBeVisible()
  Object.defineProperty(canvas, 'clientHeight', { configurable: true, value: 500 })
  act(() => resize?.())
  const large = chart.setOption.mock.lastCall?.[0]
  expect(large.yAxis[1].show).toBe(true)
  expect(large.yAxis[2].show).toBe(true)
  expect(large.xAxis[2].axisLabel.show).toBe(true)
  expect(chart.dispose).not.toHaveBeenCalled()
  mounted.unmount()
})
