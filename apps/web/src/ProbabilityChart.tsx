import { t, locale, useLanguage } from './i18n'
import { useTheme } from './theme'
import { chartColors } from './chartTheme'
import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { init, use as registerCharts, type EChartsCoreOption } from 'echarts/core'
import { LineChart, BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, AxisPointerComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { Evidence } from './researchTypes'
import type { Observation, Signal } from './marketTypes'
import { chartData, chartNumber, eventBuckets, probabilityBounds } from './chartData'
import { time } from './format'

registerCharts([LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, AxisPointerComponent, CanvasRenderer])
export type ChartViewport = { start: number; end: number } | null
export default function ProbabilityChart({ rows, signals = [], focus, onSignals, events = [], onEvidence, resetKey = 0, area = true, autoScale = false, viewport }: {
  rows: Observation[]; signals?: Signal[]; focus?: string; onSignals?: (signals: Signal[]) => void; resetKey?: number; area?: boolean; autoScale?: boolean; events?: Evidence[]; onEvidence?: (items: Evidence[]) => void; viewport?: RefObject<ChartViewport>;
}) {
  const language = useLanguage()
  const { theme } = useTheme()
  const element = useRef<HTMLDivElement>(null)
  const instance = useRef<ReturnType<typeof init> | null>(null)
  const callback = useRef(onSignals), evidenceCallback = useRef(onEvidence)
  const [cursor, setCursor] = useState<number | null>(null)
  const data = useMemo(() => chartData(rows), [rows])
  useEffect(() => { callback.current = onSignals; evidenceCallback.current = onEvidence }, [onSignals, onEvidence])
  useEffect(() => {
    if (!element.current) return
    const chart = init(element.current, undefined, { renderer: 'canvas' })
    instance.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    chart.on('click', (params: unknown) => {
      const selected = (params as { data?: { signals?: Signal[]; evidence?: Evidence[] } }).data
      if (selected?.signals) callback.current?.(selected.signals)
      if (selected?.evidence) evidenceCallback.current?.(selected.evidence)
    })
    chart.on('updateAxisPointer', (event: unknown) => {
      const axes = (event as { axesInfo?: { axisDim: string; value: number }[] }).axesInfo
      const at = axes?.find((axis) => axis.axisDim === 'x')?.value
      if (at != null) setCursor(Number(at))
    })
    chart.getZr().on('globalout', () => setCursor(null))
    chart.on('datazoom', () => {
      const zoom = (chart.getOption().dataZoom as { start: number; end: number }[])?.[0]
      if (viewport && zoom) viewport.current = { start: zoom.start, end: zoom.end }
    })
    return () => { observer.disconnect(); chart.dispose(); instance.current = null }
  }, [viewport])
  useEffect(() => {
    const chart = instance.current
    if (!chart) return
    const colors = chartColors(theme)
    const last = data.probability.at(-1)?.[1]
    const axisStyle = { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: colors.muted, fontSize: 12 }, splitLine: { lineStyle: { color: colors.grid, width: 1 } } }
    const byTime = new Map(rows.map((row) => [Date.parse(row.received_at), row]))
    const points = eventBuckets(signals, (signal) => signal.received_at).flatMap((group) => {
      const signal = group.at(-1)!, at = Date.parse(signal.received_at), row = byTime.get(at)
      return row?.probability ? [{ value: [at, row.probability.value * 100], signals: group, count: group.length, itemStyle: { color: group.every((item) => item.signal_type === 'PROBABILITY_DROP') ? colors.negative : colors.warning } }] : []
    })
    const eventPoints = eventBuckets(events, (event) => event.observed_at).flatMap((group) => {
      const at = Date.parse(group.at(-1)!.observed_at)
      const nearest = rows.reduce<Observation | null>((best, row) => !best || Math.abs(Date.parse(row.received_at) - at) < Math.abs(Date.parse(best.received_at) - at) ? row : best, null)
      return nearest?.probability && Math.abs(Date.parse(nearest.received_at) - at) <= 90000 ? [{ value: [at, nearest.probability.value * 100], evidence: group, count: group.length }] : []
    })
    const markerLabel = { show: true, position: 'top', fontSize: 10, color: colors.text, backgroundColor: colors.surface, padding: [2, 3], borderRadius: 2, formatter: (params: { data: { count: number } }) => params.data.count > 1 ? String(params.data.count) : '' }
    const bounds = autoScale ? probabilityBounds(data.probability.map((point) => point[1])) : { min: 0, max: 100 }
    const option: EChartsCoreOption = {
      backgroundColor: 'transparent', animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      animationDuration: 250, animationDurationUpdate: 200,
      textStyle: { fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace' },
      grid: [{ left: 20, right: 82, top: 18, height: '60%' }, { left: 20, right: 82, top: '69%', height: '10%' }, { left: 20, right: 82, top: '86%', height: '7%' }],
      axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: colors.pointer, color: '#ffffff' }, lineStyle: { color: colors.crosshair } },
      tooltip: { trigger: 'axis', showContent: false, axisPointer: { type: 'cross' } },
      xAxis: [0, 1, 2].map((gridIndex) => ({ ...axisStyle, gridIndex, type: 'time', boundaryGap: false, splitLine: { show: true, lineStyle: { color: colors.gridMinor } }, axisLabel: { color: colors.muted, fontSize: 11, show: gridIndex === 2, hideOverlap: true }, axisPointer: { show: true, label: { show: gridIndex === 2, formatter: (params: { value: number }) => new Date(params.value).toLocaleString(locale()) } } })),
      yAxis: [
        { ...axisStyle, gridIndex: 0, type: 'value', position: 'right', ...bounds, axisLabel: { color: colors.muted, fontSize: 12, formatter: (value: number) => chartNumber(value, '%') }, axisPointer: { label: { formatter: (params: { value: number }) => chartNumber(params.value, '%') } } },
        { ...axisStyle, gridIndex: 1, type: 'value', position: 'right', splitNumber: 2, name: `VOL · ${data.volumeUnit ?? t("N/A")}`, nameTextStyle: { color: colors.muted, fontSize: 11, align: 'right' }, axisLabel: { color: colors.muted, fontSize: 11, formatter: (value: number) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value) }, axisPointer: { label: { formatter: (params: { value: number }) => chartNumber(params.value) } } },
        { ...axisStyle, gridIndex: 2, type: 'value', position: 'right', splitNumber: 2, name: 'SPREAD · pp', nameTextStyle: { color: colors.muted, fontSize: 11, align: 'right' }, axisLabel: { color: colors.muted, fontSize: 11, formatter: (value: number) => chartNumber(value) }, axisPointer: { label: { formatter: (params: { value: number }) => chartNumber(params.value, ' pp') } } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1, 2], filterMode: 'none', zoomOnMouseWheel: true, moveOnMouseMove: true, ...(viewport?.current ?? {}) }, { type: 'slider', xAxisIndex: [0, 1, 2], show: false, bottom: 2, height: 16, borderColor: colors.border, backgroundColor: colors.zoom, fillerColor: colors.zoomFill, showDetail: false, handleSize: 12, dataBackground: { lineStyle: { color: colors.zoomLine }, areaStyle: { color: colors.zoomArea } } }],
      series: [
        { name: 'YES midpoint', type: 'line', data: data.probability, connectNulls: false, showSymbol: rows.length < 3, symbolSize: 5, lineStyle: { color: colors.line, width: 2.4 }, itemStyle: { color: colors.positive }, areaStyle: area ? { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: colors.areaTop }, { offset: 1, color: colors.areaBottom }] } } : undefined,
          markLine: { silent: true, symbol: 'none', data: last == null ? [] : [{ yAxis: last }], lineStyle: { color: colors.lastLine, type: 'dashed' }, label: { formatter: chartNumber(last, '%'), color: colors.onAccent, backgroundColor: colors.positive, padding: [4, 5], borderRadius: 3 } } },
        { name: 'News first observed', type: 'scatter', data: eventPoints, symbol: 'rect', symbolSize: 9, symbolOffset: [0, 20], label: { ...markerLabel, position: 'bottom' }, itemStyle: { color: colors.news }, cursor: 'pointer', z: 4 },
        { name: 'Signals', type: 'scatter', data: points, symbol: 'diamond', symbolSize: 11, label: markerLabel, z: 5, cursor: 'pointer', emphasis: { scale: 1.3, itemStyle: { borderColor: '#fff', borderWidth: 1 } } },
        { name: 'Sampled volume change', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: data.volume, itemStyle: { color: colors.volume }, barMaxWidth: 12 },
        { name: 'Bid/ask spread', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: data.spread, connectNulls: false, showSymbol: false, lineStyle: { color: colors.spread, width: 1.5 } },
      ],
    }
    chart.setOption(option, { replaceMerge: ['series'] })
  }, [rows, signals, events, area, autoScale, data, viewport, language, theme])
  useEffect(() => {
    if (!focus || !instance.current) return
    const at = Date.parse(focus)
    instance.current.dispatchAction({ type: 'dataZoom', startValue: at - 20 * 60000, endValue: at + 5 * 60000 })
  }, [focus])
  const previousReset = useRef(resetKey)
  useEffect(() => { if (previousReset.current !== resetKey) { instance.current?.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }); previousReset.current = resetKey } }, [resetKey])
  let row = rows.at(-1)
  if (cursor != null) {
    row = rows.reduce<Observation | undefined>((best, item) => !best || Math.abs(Date.parse(item.received_at) - cursor) < Math.abs(Date.parse(best.received_at) - cursor) ? item : best, undefined)
    if (row && Math.abs(Date.parse(row.received_at) - cursor) > 90000) row = undefined
  }
  const at = row ? Date.parse(row.received_at) : null
  return <><div className="chart-readout" aria-label={t("Chart values")}><time>{row ? time(row.received_at) : t("No observation at cursor")}</time><span className="readout-primary">{t("YES")} <b>{chartNumber(row?.probability ? row.probability.value * 100 : null, '%')}</b></span><span>{t("Δ VOL")} <b>{chartNumber(data.volume.find(([stamp]) => stamp === at)?.[1])} {data.volumeUnit ?? ''}</b></span><span>{t("SPREAD")} <b>{chartNumber(data.spread.find(([stamp]) => stamp === at)?.[1], ' pp')}</b></span></div><div ref={element} className="terminal-chart" role="img" aria-label={`YES midpoint probability, sampled volume change and bid/ask spread. ${rows.length} observations. Scroll to zoom, drag to pan; select an event group to inspect all its inputs. Events grouped in five-minute buckets. Missing intervals appear as breaks.`} /></>
}
