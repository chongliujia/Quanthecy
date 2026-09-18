import { useEffect, useRef } from 'react'
import { init, use as registerCharts } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTheme } from './theme'
import { chartColors } from './chartTheme'
import { t, useLanguage } from './i18n'
import { strategyNames, type PaperAccount } from './paperTypes'

registerCharts([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

export default function PaperEquityChart({ accounts }: { accounts: PaperAccount[] }) {
  const element = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  const language = useLanguage()
  useEffect(() => {
    if (!element.current) return
    const chart = init(element.current)
    const colors = chartColors(theme)
    chart.setOption({
      color: [colors.news, colors.line, colors.spread],
      grid: { left: 70, right: 22, top: 45, bottom: 35 },
      legend: { textStyle: { color: colors.text } },
      tooltip: { trigger: 'axis', renderMode: 'richText', valueFormatter: (value: unknown) => value == null ? '—' : Number(value).toFixed(2) },
      xAxis: { type: 'time', axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.border } } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: colors.muted }, splitLine: { lineStyle: { color: colors.grid } } },
      series: [...accounts.map(a => ({ name: a.label || t(strategyNames[a.strategy]), type: 'line', showSymbol: a.equity_history.length < 3, connectNulls: false,
        data: a.equity_history.map(p => [Date.parse(p.at), p.equity == null ? null : Number(p.equity)]) })),
      { name: t('Cash benchmark'), type: 'line', symbol: 'none', lineStyle: { type: 'dashed', color: colors.muted }, data: accounts[0]?.equity_history.map(p => [Date.parse(p.at), Number(accounts[0].initial_cash)]) ?? [] }],
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    return () => { observer.disconnect(); chart.dispose() }
  }, [accounts, theme, language])
  return <div className="paper-chart" ref={element} role="img" aria-label={t('Simulated account equity over time')} />
}
