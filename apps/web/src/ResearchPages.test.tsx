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
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 })))
  mount(<EvidenceList userId="u1" cutoff="2026-01-01T00:00:00Z" />)
  expect(await screen.findByText('No evidence available for this view')).toBeInTheDocument()
  expect(screen.getByText(/Older publication dates do not imply/)).toBeInTheDocument()
})

it('presents publisher time separately from observation time and unreviewed association', async () => {
  const item = { id: 'e1', revision_id: 'v1', version: 1, title: 'Official Fed statement', excerpt: 'Feed excerpt', url: 'https://www.federalreserve.gov/statement.htm', published_at: '2026-01-01T10:00:00Z', first_observed_at: '2026-01-02T10:00:00Z', observed_at: '2026-01-02T10:00:00Z', source_name: 'Federal Reserve', content_hash: 'sha256' }
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
