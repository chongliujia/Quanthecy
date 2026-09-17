import { useEffect, useRef } from 'react'
import { init, use as registerCharts } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { chartColors } from './chartTheme'
import { useTheme } from './theme'
import { t, useLanguage } from './i18n'
import { probability, time } from './format'
import type { EventChartData } from './eventChartTypes'

registerCharts([LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])
const issues = { missing: 'No observation', stale: 'Stale observation', invalid_quote: 'Invalid quote', contract_changed: 'Contract changed' }

export default function EventProbabilityChart({ data, view, selected, onSelection }: {
  data: EventChartData; view: 'history' | 'latest'; selected: string[]; onSelection: (ids: string[]) => void;
}) {
  const { theme } = useTheme()
  const language = useLanguage()
  const element = useRef<HTMLDivElement>(null)
  const instance = useRef<ReturnType<typeof init> | null>(null)
  const colors = chartColors(theme)
  const palette = [colors.positive, colors.news, colors.warning, colors.spread, colors.negative, theme === 'dark' ? '#b1c768' : '#657c1b']
  useEffect(() => {
    if (!element.current) return
    const chart = init(element.current)
    instance.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    return () => { observer.disconnect(); chart.dispose(); instance.current = null }
  }, [])
  useEffect(() => {
    const colors = chartColors(theme)
    const palette = [colors.positive, colors.news, colors.warning, colors.spread, colors.negative, theme === 'dark' ? '#b1c768' : '#657c1b']
    const lines = data.series.map((line, index) => {
      const contract = data.contracts.find((item) => item.id === line.market_id)!
      return { line, contract, name: `${index + 1} · ${contract.platform} · ${contract.outcome}`, color: palette[index] }
    })
    const axis = { axisLine: { lineStyle: { color: colors.border } }, axisLabel: { color: colors.muted, fontSize: 11 }, splitLine: { lineStyle: { color: colors.grid } } }
    const priceAxis = { ...axis, type: 'value', min: 0, max: 100, axisLabel: { color: colors.muted, fontSize: 11, formatter: '{value}%' } }
    instance.current?.setOption({ animation: false, textStyle: { fontFamily: 'ui-monospace, monospace' }, grid: { left: 48, right: 26, top: 20, bottom: 38 },
      tooltip: { trigger: 'axis', renderMode: 'richText', backgroundColor: colors.surface, borderColor: colors.border, textStyle: { color: colors.text, fontSize: 11 },
        formatter: (value: unknown) => {
          const entries = (Array.isArray(value) ? value : [value]) as { seriesName: string; name: string; data: { value: number | null | [number, number | null]; observed?: string | null } }[]
          return entries.map((entry) => {
            const price = Array.isArray(entry.data.value) ? entry.data.value[1] : entry.data.value
            return `${view === 'history' ? entry.seriesName : entry.name}: ${price == null ? '—' : `${price.toFixed(2)}%`}\n${t('Observed')}: ${entry.data.observed ? time(entry.data.observed) : '—'}`
          }).join('\n\n')
        } },
      xAxis: view === 'history' ? { ...axis, type: 'time', min: Date.parse(data.start), max: Date.parse(data.end), axisLabel: { color: colors.muted, fontSize: 11, hideOverlap: true } } : priceAxis,
      yAxis: view === 'history' ? priceAxis : { ...axis, type: 'category', inverse: true, data: lines.map((item) => item.name), axisLabel: { color: colors.muted, fontSize: 11, formatter: (_: string, index: number) => `${index + 1}` } },
      series: view === 'history' ? lines.map(({ line, name, color }) => ({ name, type: 'line', showSymbol: false, connectNulls: false, lineStyle: { color, width: 1.8 }, itemStyle: { color }, data: line.points.map((point) => ({ value: [Date.parse(point.at), point.probability == null ? null : point.probability * 100], observed: point.observed_at })) })) : [{ type: 'bar', barMaxWidth: 24, data: lines.map(({ line, name, color }) => ({ name, value: line.points.at(-1)?.probability == null ? null : line.points.at(-1)!.probability! * 100, observed: line.points.at(-1)?.observed_at, itemStyle: { color } })) }],
    }, { notMerge: true })
  }, [data, view, theme, language])
  const hasValues = data.series.some((line) => (view === 'history' ? line.points : line.points.slice(-1)).some((point) => point.probability != null))
  return <div className="event-chart-content"><div className="event-canvas-wrap"><div ref={element} className="event-canvas" role="img" aria-label={view === 'history' ? t('Linked contract probabilities on a shared time axis') : t('Linked contract probabilities at the research cutoff')} />{!hasValues && <div className="event-chart-empty">{t('No eligible quotes in this selection')}</div>}</div><div className="event-contracts"><div className="event-contracts-heading"><strong>{t('Linked contracts')}</strong><small>{t('Select 1–6')}</small></div>{data.contracts.map((contract) => {
    const index = data.series.findIndex((line) => line.market_id === contract.id)
    const last = data.series[index]?.points.at(-1)
    const checked = selected.includes(contract.id)
    return <label key={contract.id} className={`event-contract-choice ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} disabled={checked ? selected.length === 1 : selected.length >= 6} onChange={() => onSelection(checked ? selected.filter((id) => id !== contract.id) : [...selected, contract.id])} /><span className="event-contract-number" style={{ color: palette[index] ?? colors.muted }}>{index >= 0 ? index + 1 : '·'}</span><span><strong title={contract.title}>{contract.title}</strong><small>{contract.platform} · {contract.outcome}</small>{checked && <span className="event-contract-quote" title={`${t('Observed')}: ${last?.observed_at ? time(last.observed_at) : '—'}`}>{last?.probability != null ? probability(last.probability) : t(issues[last?.issue ?? 'missing'])}</span>}</span></label>
  })}</div></div>
}
