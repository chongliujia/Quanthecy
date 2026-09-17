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
  expect(screen.getByText(/No directly relevant official body passages have been reviewed/)).toBeVisible()
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

it('keeps feed-only direct reviews separate from forecast evidence', async () => {
  const review = { id: 'review1', relation: 'DIRECT', rationale: 'Conditional support.', paragraphs: [], reviewed_at: observed, stance: 'SUPPORTS', feed_quote: 'An exact excerpt from the feed.', target_snapshot: { market: { title: 'October rate cut?' }, outcome: { label: 'YES' } } }
  const detail: EventDetail = { ...data, official_direct_count: 0, counts: { DIRECT: 1 }, evidence: [{ ...data.evidence[0], evidence: { ...evidence, source_kind: 'MEDIA' }, status: 'DIRECT', review, history: [review], discovery: { method: 'fed-macro-v1', reasons: ['US_MACRO_TERMS'], matches: [] } }] }
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(detail)))
  mount(<EventPages userId="u1" slug={event.slug} cutoff="" />)
  expect(await screen.findByText('Supports the selected outcome')).toBeVisible()
  expect(screen.getByText('October rate cut? · YES')).toBeVisible()
  expect(screen.getByText(/No directly relevant official body passages have been reviewed/)).toBeVisible()
  fireEvent.click(screen.getByText('Why this is a candidate'))
  expect(screen.getByText('US macroeconomic terms in saved text')).toBeVisible()
})

it('shows historical removals with a link to the previous version', () => {
  mount(<FrozenEvidence reference={{ id: 'r1', kind: 'evidence', label: 'Fed', value: { evidence, version_changes: { kind: 'REVISION', previous_observed_at: '2026-09-15T10:00:00+00:00', changed_fields: ['document'], added: [], removed: [{ paragraph: 2, text: 'Old qualification.', truncated: false }] }, event_reviews: [{ event_slug: 'fed', review: { id: 'rev', relation: 'DIRECT', rationale: 'Saved judgment', stance: 'OPPOSES', stance_applicable: false } }] } }} />)
  expect(screen.getByText('This saved stance does not apply to the current contract and rules.')).toBeVisible()
  fireEvent.click(screen.getByText('What changed in this saved version'))
  expect(screen.getByText('Removed from the current capture')).toBeVisible()
  expect(screen.getByRole('link', { name: /Previous version/ })).toHaveAttribute('href', `#/evidence/e1?cutoff=${encodeURIComponent('2026-09-15T10:00:00+00:00')}&paragraph=2`)
})
