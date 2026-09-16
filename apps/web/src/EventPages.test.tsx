import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import EventPages, { FrozenEvidence, type EventDetail } from './EventPages'
import OfficialDocumentPanel from './OfficialDocumentPanel'
import { setLanguage } from './i18n'

const observed = '2026-09-16T13:00:00.123456+00:00'
const event = { id: 'ev1', slug: 'fed-october', version: 1, title: 'October Fed decision', title_zh: '十月美联储决议', scope: 'October outcome.', scope_zh: '十月结果。', starts_on: '2026-10-27', ends_on: '2026-10-28', calendar_url: 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm', observed_at: observed, market_count: 1 }
const evidence = { id: 'e1', revision_id: 'r1', title: 'Fed statement', excerpt: 'Summary', version: 2, source_slug: 'fed-monetary', source_name: 'Fed', url: event.calendar_url, published_at: observed, first_observed_at: observed, observed_at: observed, content_hash: 'hash' }
const data: EventDetail = { event, cutoff: observed, markets: [], changes: [], counts: { PENDING: 1, DIRECT: 0, BACKGROUND: 0, STALE: 0, UNRELATED: 0 }, truncated: false, evidence: [{ id: 'c1', evidence, status: 'PENDING', review: null, passages: [], history: [], matched_at: observed }] }
function mount(content: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{content}</QueryClientProvider>) }

it('separates pending candidates from approvals and preserves exact evidence cutoff', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(data)))
  mount(<EventPages userId="u1" slug={event.slug} cutoff="" />)
  expect(await screen.findByText('October Fed decision')).toBeInTheDocument()
  expect(screen.getByText(/No directly relevant evidence has been reviewed/)).toBeVisible()
  expect(screen.getByRole('link', { name: 'Fed statement' })).toHaveAttribute('href', `#/evidence/e1?cutoff=${encodeURIComponent(observed)}`)
  fireEvent.change(screen.getByLabelText('Relevance filter'), { target: { value: 'DIRECT' } })
  expect(screen.getByText('No evidence in this category.')).toBeVisible()
  expect(screen.queryByRole('link', { name: 'Fed statement' })).not.toBeInTheDocument()
})

it('keeps the historical cutoff when opening a bilingual event dossier', async () => {
  setLanguage('zh')
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([event])))
  mount(<EventPages userId="u1" cutoff={observed} />)
  expect(await screen.findByRole('link', { name: /十月美联储决议/ })).toHaveAttribute('href', `#/events/fed-october?cutoff=${encodeURIComponent(observed)}`)
})

it('links report passages to the cited version and original paragraph', () => {
  mount(<FrozenEvidence reference={{ id: 'r1', kind: 'evidence', label: 'Fed', value: { evidence, document_selection: { passages: [{ paragraph: 12, text: 'Frozen qualification.', truncated: true }] } } }} />)
  expect(screen.getByRole('link', { name: 'Paragraph 12 ↗' })).toHaveAttribute('href', `#/evidence/e1?cutoff=${encodeURIComponent(observed)}&paragraph=12`)
  expect(screen.getByText('Frozen qualification.…')).toBeVisible()
})

it('opens and highlights a cited paragraph beyond the initial preview', () => {
  window.history.replaceState(null, '', '/#/evidence/e1?paragraph=12')
  mount(<OfficialDocumentPanel historical document={{ title: 'Statement', kind: 'MONETARY_RELEASE', url: event.calendar_url, observed_at: observed, extractor_version: 'v1', raw_sha256: 'hash', text_sha256: 'hash', text: Array.from({ length: 14 }, (_, i) => `Original paragraph ${i + 1}`).join('\n\n') }} />)
  expect(screen.getByText('Original paragraph 12')).toHaveClass('selected-paragraph')
  expect(screen.getByRole('button', { name: 'Show fewer paragraphs' })).toBeVisible()
})

it('supports retrying event API errors', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Event data unavailable'))
  mount(<EventPages userId="u1" cutoff="" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Event data unavailable')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible()
})

it('switches between evidence and changes without a long scroll', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(data)))
  mount(<EventPages userId="u1" slug={event.slug} cutoff="" />)
  expect(await screen.findByText('October Fed decision')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Evidence changes' }))
  expect(screen.getByRole('heading', { name: 'Evidence changes' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'Evidence for this event' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Evidence for this event' }))
  expect(screen.getByRole('link', { name: 'Fed statement' })).toBeVisible()
})
