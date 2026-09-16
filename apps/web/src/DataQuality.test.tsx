import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import DataQuality from './DataQuality'
import { setLanguage } from './i18n'

it('explains unavailable indicators and known limits in both languages', () => {
  const quality = { version: 'research-quality-v1', checked_at: '2026-01-01T12:15:00Z', state: 'limited' as const, price_usable: true, volume_usable: false, reasons: ['volume_counter_reset'], limitations: ['source_time_missing'], age_seconds: 1 }
  setLanguage('en')
  const view = render(<DataQuality quality={quality} />)
  expect(screen.getByText(/Some indicators unavailable/)).toBeInTheDocument()
  expect(screen.getByText('Cumulative volume counter reset')).toBeInTheDocument()
  expect(screen.getByText(/Exchange timestamp unavailable/)).toBeInTheDocument()
  setLanguage('zh')
  view.rerender(<DataQuality quality={quality} />)
  expect(screen.getByText('累计成交量计数器回退')).toBeInTheDocument()
  expect(screen.getByText(/成交量异常.*不可计算/)).toBeInTheDocument()
  expect(screen.getByText(/数据准入状态不代表预测准确率/)).toBeInTheDocument()
  setLanguage('en')
})
