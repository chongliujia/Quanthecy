import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import AgentPanel from './AgentPanel'
import { ForecastView } from './IntelligenceView'
import { setLanguage } from './i18n'
import type { AgentRun, ResearchSkill } from './agentTypes'

const organization = { id: 'org1', name: 'Desk', slug: 'desk', kind: 'PERSONAL', role: 'OWNER' as const }
const skills: ResearchSkill[] = ['quant', 'events', 'pricing', 'risk', 'synthesis'].map(id => ({ id, name: id, responsibility: id, reference_kinds: ['market'], dependencies: [], version: '1.0.0' }))
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AgentPanel userId="u1" organization={organization} marketId="m1" cutoff="2026-01-01T12:00:00Z" /></QueryClientProvider>) }
function mockApi(used = 0) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input)
    if (init?.method === 'POST') return new Response(JSON.stringify({ id: 'new-run' }))
    return new Response(JSON.stringify(path.endsWith('/status') ? { enabled: true, model: 'test-model', can_manage: true, can_run: true, runs_today: used, daily_run_limit: 10 } : path.endsWith('/skills') ? skills : []))
  })
}

it('shows five-call cost before an explicit team request and sends the selected language', async () => {
  const fetch = mockApi()
  setLanguage('zh')
  mount()
  const button = await screen.findByRole('button', { name: '✧ 分析此市场' })
  await waitFor(() => expect(button).toBeEnabled())
  expect(screen.getByText(/预留最多 5 次模型请求/)).toBeVisible()
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  fireEvent.click(button)
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const sent = fetch.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({ workflow: 'team', language: 'zh', cutoff: '2026-01-01T12:00:00Z' })
})

it('blocks a five-call team request when only four calls remain but allows quick research', async () => {
  mockApi(6)
  mount()
  const button = await screen.findByRole('button', { name: '✧ Analyze this market' })
  expect(button).toBeDisabled()
  expect(screen.getByText('Not enough daily request capacity for this workflow.')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Quick research' }))
  expect(button).toBeEnabled()
  expect(screen.getByText(/Reserves up to 1 model requests/)).toBeVisible()
})

it('renders abstention separately from observed probability and never substitutes zero', () => {
  const rationale = { kind: 'HYPOTHESIS' as const, text: 'Missing event evidence', references: ['market'] }
  const run: AgentRun = {
    id: 'r1', market_id: 'm1', kind: 'RESEARCH', state: 'SUCCEEDED', stage: 'completed',
    cutoff: '2026-01-01T12:00:00Z', configuration_revision: 1, model: 'test',
    prompt_version: 'research-team-v1', usage: {}, error_code: '', created_at: '', finished_at: null,
    report: { action: 'WATCH', confidence: 0.6, thesis: rationale, claims: [], counter_evidence: [], key_signals: [], risk_flags: [], follow_up: [], forecast: { status: 'ABSTAIN', target: 'YES_AT_CONTRACT_RESOLUTION', calibration: 'UNCALIBRATED', probability: null, lower: null, upper: null, rationale, assumptions: [], invalidation_triggers: [] } },
    context: { references: [{ id: 'market', kind: 'market', label: 'Market quote', value: { probability: { value: 0.52, basis: 'MIDPOINT' } } }], limitations: [] },
  }
  render(<ForecastView run={run} claim={item => <p>{item.text}</p>} />)
  expect(screen.getByText('52.00%')).toBeVisible()
  expect(screen.getByText('Abstain')).toBeVisible()
  expect(screen.getByText('Uncalibrated')).toBeVisible()
  expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
})
