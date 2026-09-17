import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ComparisonList, ComparisonView, EvidenceList, EvidenceView, SignalFeed } from './ResearchPages'
import App from './App'

vi.mock('./ComparisonChart', () => ({ default: () => <div>Comparison chart</div> }))
const frozen = { platform: 'polymarket', market: { id: 'm1', title: 'Fed hold?', resolution_rules: 'Settlement terms', closes_at: null, rules_version: 'v1' }, outcome: { label: 'Yes' } }
const review = { id: 'r1', comparison_id: 'p1', title: 'Fed holds rates', topic: 'Macro & rates', version: 1, relation: 'RELATED', alignment: 'SAME', rationale: 'Same scheduled meeting', differences: 'Cancellation fallback differs.', reviewer_label: 'Source review', confidence: 0.9, reviewed_at: '2026-01-01T12:00:00Z', left_snapshot: frozen, right_snapshot: { ...frozen, platform: 'kalshi', market: { ...frozen.market, id: 'm2' } } }

function mount(content: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{content}</QueryClientProvider>) }

it('keeps historical cutoff in comparison detail links', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([review])))
  const cutoff = '2026-01-01T13:00:00Z'
  mount(<ComparisonList userId="u1" cutoff={cutoff} />)
  expect(await screen.findByRole('link', { name: /Fed holds rates/ })).toHaveAttribute('href', `#/comparisons/p1?cutoff=${encodeURIComponent(cutoff)}`)
  expect(fetch).toHaveBeenCalledWith(`/api/v1/comparisons?cutoff=${encodeURIComponent(cutoff)}`, expect.anything())
  expect(screen.getByText('Historical view')).toBeInTheDocument()
})

it('shows exclusion reasons without inventing a zero difference', async () => {
  const point = { at: '2026-01-01T13:00:00Z', difference: null, left: null, right: null, skew_seconds: null, issues: ['LEFT_STALE', 'RIGHT_NO_PRICE'], review_version: 1 }
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes('/timeline') ? { items: [], truncated: false } : { review, revisions: [review], cutoff: point.at, current: point, history: [point], max_age_seconds: 180, max_skew_seconds: 90 })))
  mount(<ComparisonView userId="u1" id="p1" cutoff="" />)
  expect(await screen.findByText('Difference unavailable')).toBeInTheDocument()
  expect(screen.getByText('left stale')).toBeInTheDocument()
  expect(screen.getAllByText('Cancellation fallback differs.')[0]).toBeVisible()
  expect(screen.queryByText('0.00 pp')).not.toBeInTheDocument()
  expect(screen.queryByText('Comparison chart')).not.toBeInTheDocument()
})

it('explains evidence collection cutoff for an empty historical feed', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).includes('/research/sources') ? { sources: [], polling_enabled: true } : { items: [], total: 0 })))
  mount(<EvidenceList userId="u1" cutoff="2026-01-01T00:00:00Z" />)
  expect(await screen.findByText('No evidence available for this view')).toBeInTheDocument()
  expect(screen.getByText(/Older publication dates do not imply/)).toBeInTheDocument()
})

it('presents publisher time separately from observation time and unreviewed association', async () => {
  const item = { id: 'e1', revision_id: 'v1', version: 1, title: 'Official Fed statement', excerpt: 'Feed excerpt', url: 'https://www.federalreserve.gov/statement.htm', published_at: '2026-01-01T10:00:00Z', first_observed_at: '2026-01-02T10:00:00Z', observed_at: '2026-01-02T10:00:00Z', source_name: 'Federal Reserve', source_kind: 'OFFICIAL', content_hash: 'sha256' }
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ item, revisions: [item], links: [{ id: 'l1', market_id: 'm1', status: 'TOPIC_ONLY', rationale: 'Topic wording only', method: 'fed-topic-v1', created_at: '2026-01-02T11:00:00Z' }] })))
  mount(<EvidenceView userId="u1" id="e1" cutoff="" />)
  expect(await screen.findByText('Official Fed statement')).toBeInTheDocument()
  expect(screen.getByText('topic only')).toBeInTheDocument()
  expect(screen.getByText(/publisher's publication date is stored separately/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Official source ↗' })).toHaveAttribute('rel', 'noopener noreferrer')
})

it('supports recoverable signal-feed errors', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Historical data unavailable'))
  mount(<SignalFeed userId="u1" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Historical data unavailable')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

it('filters media sources and shows current collection problems separately from history', async () => {
  const source = { slug: 'bbc-business', name: 'BBC · Business', kind: 'MEDIA', url: 'https://feeds.bbci.co.uk/news/business/rss.xml', enabled: true, status: 'retrying', poll_interval_seconds: 900, last_success_at: null, latest_published_at: null, last_entry_count: 0, last_rejected_count: 0, last_duplicate_count: 0, last_undated_count: 0, error: 'Feed refresh failed (HTTP 429); stored evidence retained.' }
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).includes('/research/sources') ? { sources: [source], polling_enabled: true } : { items: [], total: 0 })))
  mount(<EvidenceList userId="u1" cutoff="2026-01-02T00:00:00Z" />)
  expect(await screen.findByRole('option', { name: 'BBC · Business' })).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: 'Source type' }), { target: { value: 'MEDIA' } })
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).includes('kind=MEDIA'))).toBe(true))
  fireEvent.click(screen.getByText(/News source coverage/))
  expect(screen.getByText('Collection retrying')).toBeVisible()
  expect(screen.getByText(/Current collection status/)).toBeVisible()
  expect(screen.getByText('15 minutes')).toBeVisible()
})

it('does not call media an official source or promise a pending full article', async () => {
  const item = { id: 'e2', revision_id: 'v1', version: 1, title: 'Fed policy reporting', excerpt: 'A media excerpt', url: 'https://www.bbc.co.uk/news/example', published_at: null, first_observed_at: '2026-01-02T10:00:00Z', observed_at: '2026-01-02T10:00:00Z', source_name: 'BBC · Business', source_kind: 'MEDIA', document_supported: false, quality_flags: ['PUBLICATION_TIME_UNKNOWN'], content_hash: 'sha256' }
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ item, revisions: [item], links: [] })))
  mount(<EvidenceView userId="u1" id="e2" cutoff="2026-01-03T00:00:00Z" />)
  expect(await screen.findByRole('link', { name: 'Original source ↗' })).toHaveAttribute('href', item.url)
  expect(screen.queryByRole('link', { name: 'Official source ↗' })).not.toBeInTheDocument()
  expect(screen.getByText(/Full article text is not collected/)).toBeVisible()
  expect(screen.getByText(/collection time is not a substitute/)).toBeVisible()
  expect(screen.queryByText('Official document text')).not.toBeInTheDocument()
})

it('opens shared routes directly and responds to browser navigation', async () => {
  window.history.replaceState(null, '', '/#/comparisons')
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    return new Response(JSON.stringify(path.endsWith('/me') ? { id: 'u1', email: 'u@example.com' } : path.includes('/organizations?') ? [] : path.includes('/evidence?') ? { items: [], total: 0 } : []))
  })
  mount(<App />)
  expect(await screen.findByRole('heading', { name: 'Cross-platform' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('link', { name: /News & evidence/ }))
  expect(await screen.findByRole('heading', { name: 'News & evidence' })).toBeInTheDocument()
  window.history.replaceState(null, '', '/#/comparisons')
  fireEvent(window, new HashChangeEvent('hashchange'))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Cross-platform' })).toBeInTheDocument())
})
