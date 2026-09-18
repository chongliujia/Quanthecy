import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { Organization } from './api'
import PaperLab from './PaperLab'
import type { PaperLabData } from './paperTypes'
import { setLanguage } from './i18n'

vi.mock('./PaperEquityChart', () => ({ default: () => <div>Equity chart</div> }))
const organization: Organization = { id: 'org1', name: 'Research', slug: 'research', kind: 'TEAM', role: 'OWNER' }
const candidate = { id: 'm1', platform: 'polymarket', title: 'Election market', event: 'Election', bid: .49, ask: .5 }
function respond(body: unknown) { return new Response(JSON.stringify(body)) }
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
function sample(): PaperLabData {
  return { id: 'e1', name: 'Research experiment', running: true, version: 'paper-v1', settings: {}, checked_at: new Date().toISOString(), created_at: '2026-09-18T00:00:00Z', error_code: '', collector: {}, market_count: 1,
    accounts: [{ id: 'a1', platform: 'polymarket', strategy: 'momentum', initial_cash: '10000', cash: '9900', reserved_cash: '0', equity: null, realized_pnl: '0', unrealized_pnl: null, fees: '1', max_drawdown: '0', unpriced_positions: 1, equity_at: new Date().toISOString(), fills: 1, orders: 1, equity_history: [] }], positions: [], recent_orders: [], recent_decisions: [] }
}
function mockApi(lab: PaperLabData | null = null) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    if (String(input).endsWith('/auth/csrf')) return respond({ csrf_token: 'test' })
    if (String(input).endsWith('/candidates')) return respond([candidate])
    return respond(lab)
  })
}
it('requires an explicit workspace before requesting paper accounts', () => {
  const fetch = mockApi()
  render(<PaperLab userId="u1" />, { wrapper: wrapper() })
  expect(screen.getByText('Select a workspace to use paper trading.')).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})
it('starts a localized experiment with explicit workspace, universe and virtual funds', async () => {
  const fetch = mockApi()
  setLanguage('zh')
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  await screen.findByText('Election market')
  fireEvent.change(screen.getByLabelText('每个账户的初始虚拟资金'), { target: { value: '5000' } })
  fireEvent.click(screen.getByRole('button', { name: '启动模拟实验' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/paper', expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: '模拟交易实验', market_ids: ['m1'], initial_cash: '5000', version: 'paper-v2', daily_review_limit: 10 }), headers: expect.objectContaining({ 'X-CSRFToken': 'test' }) })))
})
it('prevents a viewer from starting or pausing experiments', async () => {
  mockApi()
  const view = render(<PaperLab userId="u1" organization={{ ...organization, role: 'VIEWER' }} />, { wrapper: wrapper() })
  expect(await screen.findByRole('button', { name: 'Start paper experiment' })).toBeDisabled()
  expect(screen.getByLabelText('Initial virtual capital per account')).toBeDisabled()
  view.unmount()
  vi.restoreAllMocks()
  mockApi(sample())
  render(<PaperLab userId="u1" organization={{ ...organization, role: 'VIEWER' }} />, { wrapper: wrapper() })
  expect(await screen.findByRole('button', { name: 'Pause experiment' })).toBeDisabled()
})
it('shows unavailable equity instead of manufacturing a zero valuation or profit', async () => {
  mockApi(sample())
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  expect(await screen.findByText('Valuation unavailable')).toBeVisible()
  expect(screen.getByText(/positions awaiting valuation/)).toBeVisible()
  expect(screen.queryByText('-10000.00')).not.toBeInTheDocument()
})
it('clears experiment data and selection when switching workspaces', async () => {
  const fetch = mockApi(sample())
  const view = render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  await screen.findByText('Research experiment')
  fetch.mockImplementation(async input => respond(String(input).endsWith('/candidates') ? [] : null))
  view.rerender(<PaperLab userId="u1" organization={{ ...organization, id: 'org2' }} />)
  await screen.findByText('Start a prospective experiment')
  expect(screen.queryByText('Research experiment')).not.toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org2/paper', expect.anything())
})
it('pauses through the authenticated workspace API', async () => {
  const fetch = mockApi(sample())
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: 'Pause experiment' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/paper', expect.objectContaining({ method: 'PATCH', body: '{"running":false,"experiment_id":"e1"}', headers: expect.objectContaining({ 'X-CSRFToken': 'test' }) })))
})

function reviewedSample(): PaperLabData {
  return { ...sample(), version: 'paper-v2', is_latest: true,
    experiments: [{ id: 'e2', name: 'v2', version: 'paper-v2', running: true, created_at: '2026-09-18T01:00:00Z' }, { id: 'e1', name: 'v1', version: 'paper-v1', running: false, created_at: '2026-09-18T00:00:00Z' }],
    review_summary: { model_ready: false, model: '', daily_limit: 10, calls_today: 0, calls_remaining: 10, candidates: 1, reviewed: 0, allowed: 0, rejected: 0, abstained: 0, invalidated: 0, failed: 0, waiting: 1, paired_candidates: 1, paired_agent_entries: 0, participation: 0, provider_calls: 0, prompt_tokens: 0, completion_tokens: 0, average_latency_seconds: null, average_queue_seconds: null, model_cost_usd: null },
    recent_reviews: [{ id: 'r1', market_id: 'm1', title: 'Election review', detected_at: '2026-09-18T01:00:00Z', expires_at: '2026-09-18T01:10:00Z', state: 'WAITING', reason: 'review_model_unavailable', run_state: null, review_decision: null, model: null, error_code: '', baseline_filled: true, agent_filled: false }] }
}
it('explains disabled models, review participation and unknown model charges', async () => {
  mockApi(reviewedSample())
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  expect(await screen.findByRole('heading', { name: 'Automatic entry reviews' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Model settings' })).toHaveAttribute('href', '#/model-settings')
  expect(screen.getByText('0.0% (0/1)')).toBeVisible()
  expect(screen.getByText('Unavailable')).toBeVisible()
  expect(screen.queryByText('Agent reports are reused from this workspace. This experiment does not automatically request paid model calls. Missing reports cause abstention.')).not.toBeInTheDocument()
})
it('loads the selected historical experiment and disables its resume action', async () => {
  const data = reviewedSample()
  const fetch = mockApi(data)
  fetch.mockImplementation(async input => respond(String(input).includes('experiment_id=e1') ? { ...data, id: 'e1', version: 'paper-v1', running: false, is_latest: false, review_summary: null } : data))
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  fireEvent.change(await screen.findByLabelText('Experiment history'), { target: { value: 'e1' } })
  expect(await screen.findByRole('button', { name: 'Resume experiment' })).toBeDisabled()
  expect(screen.getByText(/Historical experiment: new entries are stopped/)).toBeVisible()
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/paper?experiment_id=e1', expect.anything())
})
it('starts a new version without replacing the old account data', async () => {
  const fetch = mockApi({ ...sample(), is_latest: true })
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: 'Start v2 and preserve v1' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/paper/upgrade', expect.objectContaining({ method: 'POST', body: '{"daily_review_limit":10}' })))
})
it('shows separate cautions, blockers and frozen evidence in review details', async () => {
  const data = reviewedSample()
  mockApi(data).mockImplementation(async input => String(input).includes('/opportunities/r1') ? respond({ ...data.recent_reviews![0], inputs: {}, context: {}, usage: {}, finished_at: null, report: { decision: 'ALLOW', rationale: { text: 'The test is supported.', references: ['paper-entry'] }, blocking_risks: [], cautions: [{ text: 'Ordinary price uncertainty.', references: ['paper-entry'] }], missing_evidence: [] } }) : respond(data))
  render(<PaperLab userId="u1" organization={organization} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect entry review' }))
  expect(await screen.findByText('The test is supported.')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Blocking risks' })).toBeVisible()
  expect(screen.getByText('Ordinary price uncertainty.')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'General cautions' })).toBeVisible()
})
