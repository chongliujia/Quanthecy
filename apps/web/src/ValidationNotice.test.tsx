import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import ValidationNotice from './ValidationNotice'
import { setLanguage } from './i18n'

it('shows the failed expert and specific field without raw provider text', () => {
  setLanguage('zh')
  render(<ValidationNotice stage="Quantitative analyst" issues={[{ field: 'summary.references', code: 'unknown_reference' }]} />)
  expect(screen.getByRole('alert')).toHaveTextContent('失败阶段: 量化分析师')
  expect(screen.getByText('summary.references')).toBeVisible()
  expect(screen.getByText('引用不在这位专家可使用的证据 ID 列表中。')).toBeVisible()
  expect(screen.getByText('未发布报告，也未自动重试模型请求。')).toBeVisible()
})

it('does not invent a validation reason for a historical run', () => {
  render(<ValidationNotice />)
  expect(screen.getByText(/This older run did not record/)).toBeVisible()
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})
