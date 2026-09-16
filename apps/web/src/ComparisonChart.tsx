import { t, useLanguage } from './i18n'
import { useTheme } from './theme'
import { chartColors } from './chartTheme'
import { useEffect, useRef } from 'react'
import { init, use as registerCharts } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { Point } from './researchTypes'

registerCharts([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

export default function ComparisonChart({ points, left, right }: { points: Point[]; left: string; right: string }) {
  const { theme } = useTheme()
  const language = useLanguage()
  const element = useRef<HTMLDivElement>(null)
  const instance = useRef<ReturnType<typeof init> | null>(null)
  useEffect(() => {
    if (!element.current) return
    const chart = init(element.current)
    instance.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    return () => { observer.disconnect(); chart.dispose(); instance.current = null }
  }, [])
  useEffect(() => {
    const chart = instance.current
    if (!chart) return
    const colors = chartColors(theme)
    chart.setOption({ animation: false, color: [colors.positive, colors.warning], legend: { bottom: 0, textStyle: { color: colors.muted } },
      grid: { left: 48, right: 18, top: 20, bottom: 60 }, tooltip: { trigger: 'axis', backgroundColor: colors.surface, borderColor: colors.border, textStyle: { color: colors.text }, valueFormatter: (value: number | null) => value == null ? t("Unavailable") : `${value.toFixed(2)}%` },
      xAxis: { type: 'time', axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.border } } }, yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: colors.muted }, splitLine: { lineStyle: { color: colors.grid } } },
      series: (['left', 'right'] as const).map((side, i) => ({ name: i ? right : left, type: 'line', connectNulls: false, showSymbol: points.filter((point) => point.difference !== null).length < 20, symbolSize: 5,
        data: points.map((point) => [Date.parse(point.at), point.difference == null || point[side]?.probability == null ? null : point[side]!.probability! * 100]) })),
    })
  }, [points, left, right, theme, language])
  return <div ref={element} className="probability-chart" role="img" aria-label={t("Aligned probabilities for both contracts. Only qualified pairs of observations are shown; missing intervals remain blank. Recent values are available in the table below.")} />
}
