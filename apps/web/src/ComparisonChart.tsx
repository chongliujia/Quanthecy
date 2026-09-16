import { t } from './i18n'
import { useEffect, useRef } from 'react'
import { init, use as registerCharts } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { Point } from './researchTypes'

registerCharts([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

export default function ComparisonChart({ points, left, right }: { points: Point[]; left: string; right: string }) {
  const element = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!element.current) return
    const chart = init(element.current)
    chart.setOption({ animation: false, color: ['#50d6c5', '#deb574'], legend: { bottom: 0, textStyle: { color: '#92a8bd' } },
      grid: { left: 48, right: 18, top: 20, bottom: 60 }, tooltip: { trigger: 'axis', backgroundColor: '#142230', borderColor: '#334659', textStyle: { color: '#d6e3ef' }, valueFormatter: (value: number | null) => value == null ? t("Unavailable") : `${value.toFixed(2)}%` },
      xAxis: { type: 'time', axisLabel: { color: '#8096af' }, axisLine: { lineStyle: { color: '#2a3a4a' } } }, yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#8096af' }, splitLine: { lineStyle: { color: '#243142' } } },
      series: (['left', 'right'] as const).map((side, i) => ({ name: i ? right : left, type: 'line', connectNulls: false, showSymbol: points.filter((point) => point.difference !== null).length < 20, symbolSize: 5,
        data: points.map((point) => [Date.parse(point.at), point.difference == null || point[side]?.probability == null ? null : point[side]!.probability! * 100]) })),
    })
    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element.current)
    return () => { observer.disconnect(); chart.dispose() }
  }, [points, left, right])
  return <div ref={element} className="probability-chart" role="img" aria-label={t("Aligned probabilities for both contracts. Only qualified pairs of observations are shown; missing intervals remain blank. Recent values are available in the table below.")} />
}
