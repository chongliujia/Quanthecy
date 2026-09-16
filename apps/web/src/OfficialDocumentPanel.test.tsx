import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import OfficialDocumentPanel from './OfficialDocumentPanel'

const document = {
  title: 'Official speech', kind: 'SPEECH' as const,
  url: 'https://www.federalreserve.gov/newsevents/speech/example20260903a.htm',
  observed_at: '2026-09-16T14:00:00Z', extractor_version: 'fed-article-v1',
  raw_sha256: 'raw-hash', text_sha256: 'text-hash',
  text: Array.from({ length: 10 }, (_, index) => `Paragraph content ${index + 1}`).join('\n\n'),
}

it('distinguishes official speech, capture time and omitted paragraphs', () => {
  render(<OfficialDocumentPanel document={document} historical={false} />)
  expect(screen.getByText("A speaker's views are not a committee decision. Topic relevance does not establish a cause for market movements.")).toBeInTheDocument()
  expect(screen.getByText(/Text captured at/)).toBeInTheDocument()
  expect(screen.queryByText('Paragraph content 10')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Read all 10 paragraphs' }))
  expect(screen.getByText('Paragraph content 10')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open official document ↗' })).toHaveAttribute('rel', 'noopener noreferrer')
})

it('explains absence at historical cutoff without claiming the source did not exist', () => {
  render(<OfficialDocumentPanel document={null} historical />)
  expect(screen.getByText('No official document text had been captured at this cutoff. The feed excerpt remains available above.')).toBeInTheDocument()
  expect(screen.queryByText('Text captured')).not.toBeInTheDocument()
})

it('preserves saved text after refresh failure and renders content as text', () => {
  const { container } = render(<OfficialDocumentPanel document={{ ...document, text: '<script>untrusted()</script>' }} historical={false}
    collection={{ state: 'retrying', error: 'document_fetch_failed', last_checked_at: null, last_success_at: null, next_poll_at: '2026-09-16T15:00:00Z' }} />)
  expect(screen.getByText(/latest document refresh failed/)).toBeInTheDocument()
  expect(screen.getByText('<script>untrusted()</script>')).toBeInTheDocument()
  expect(container.querySelector('script')).toBeNull()
})
