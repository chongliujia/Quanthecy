import { act, render } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import ProbabilityChart from './ProbabilityChart'
import ComparisonChart from './ComparisonChart'
import { setThemePreference } from './theme'
import type { ChartViewport } from './ProbabilityChart'

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
