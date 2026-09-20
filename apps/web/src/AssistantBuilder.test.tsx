import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AssistantBuilder from './AssistantBuilder'
import AssistantNodeInspector from './AssistantNodeInspector'
import { canConnect, arrangeGraph, connectionError, freeNodePosition, graphDirection, graphIssues } from './assistantGraph'
import { useState } from 'react'
import AssistantCanvas from './AssistantCanvas'
import AssistantComparison from './AssistantComparison'
import type { Assistant, AssistantGraph } from './assistantTypes'
import type { Organization } from './api'

const org: Organization = { id: 'org1', name: 'Research', slug: 'research', role: 'OWNER', kind: 'TEAM' }
const graph: AssistantGraph = { schema_version: 1, entry_change_15m: .02, nodes: [
  { id: 'quant', kind: 'quant', label: 'Quantitative analyst', instructions: '', x: 50, y: 50 },
  { id: 'risk', kind: 'risk', label: 'Risk reviewer', instructions: '', x: 50, y: 220 },
  { id: 'review', kind: 'review', label: 'Entry reviewer', instructions: '', x: 50, y: 400 },
], edges: [{ source: 'quant', target: 'risk' }, { source: 'risk', target: 'review' }] }
const assistant: Assistant = { id: 'a1', name: 'My team', draft: graph, revision: 1, is_default: false, versions: [], updated_at: '2026-09-18T12:00:00Z' }
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
const response = (value: unknown) => new Response(JSON.stringify(value))
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  // jsdom does not implement the transform matrix used by React Flow to measure ports.
  vi.stubGlobal('DOMMatrixReadOnly', class { m22 = 1 })
})

function setup() {
  let saved = structuredClone(assistant)
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const path = String(url)
    if (path.endsWith('/auth/csrf')) return response({ csrf_token: 'test' })
    if (path.endsWith('/candidates')) return response([{ id: 'm1', title: 'Election market' }])
    if (path.endsWith('/agent/status')) return response({ can_run: true, enabled: true, model: 'fixture', daily_run_limit: 20, runs_today: 0, max_output_tokens: 4096 })
    if (path.endsWith('/paper/policy')) return response({ entry_change_15m: '.02', market_budget_fraction: '.01', event_budget_fraction: '.02', max_spread: '.08', max_quote_age_seconds: 90, holding_minutes: 60 })
    if (path.endsWith('/publish')) return response({ id: 'v1', assistant_id: 'a1', number: 1, name: saved.name, graph: saved.draft, graph_hash: 'abc', runtime_version: 'paper-assistant-v1', created_at: '2026-09-18T12:00:00Z' })
    if (path.endsWith('/a1') && init?.method === 'PUT') {
      const payload = JSON.parse(String(init.body))
      saved = { ...saved, name: payload.name, draft: payload.graph, revision: saved.revision + 1 }
      return response(saved)
    }
    return response([saved])
  })
}

it('saves current prompts before publishing and passes the frozen version to comparison', async () => {
  const fetch = setup(), onCompare = vi.fn()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={onCompare} />, { wrapper: wrapper() })
  fireEvent.change(await screen.findByLabelText('Node prompt'), { target: { value: 'Check settlement wording.' } })
  fireEvent.click(screen.getByRole('button', { name: /Publish version/ }))
  await screen.findByText(/Version published/)
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/assistants/a1', expect.objectContaining({ method: 'PUT', body: expect.stringContaining('"prompt":"Check settlement wording."') }))
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/assistants/a1/publish', expect.objectContaining({ body: '{"revision":2}' }))
  fireEvent.click(screen.getByRole('button', { name: /Add to comparison/ }))
  expect(onCompare).toHaveBeenCalledWith('v1')
  expect(fetch.mock.calls.filter(([path]) => String(path).endsWith('/trial'))).toHaveLength(0)
})

it('keeps viewer prompts, skills and trials read-only', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={{ ...org, role: 'VIEWER' }} onCompare={vi.fn()} />, { wrapper: wrapper() })
  expect(await screen.findByLabelText('Node prompt')).toBeDisabled()
  expect(screen.getByRole('button', { name: /Publish version/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('tab', { name: /Skills/ }))
  expect(screen.getByRole('button', { name: /New skill/ })).toBeDisabled()
  expect(screen.getByLabelText('Upload skill files')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Trial run' }))
  expect(await screen.findByRole('button', { name: /Run saved draft/ })).toBeDisabled()
})

it('moves nodes with keyboard access and rejects cycles or a risk bypass', () => {
  const onChange = vi.fn()
  render(<AssistantCanvas graph={graph} onChange={onChange} selected="quant" onSelect={vi.fn()} />)
  fireEvent.keyDown(screen.getByRole('button', { name: 'Select node Quantitative analyst' }), { key: 'ArrowRight' })
  expect(onChange.mock.lastCall?.[0].nodes[0].x).toBe(70)
  expect(canConnect(graph, 'review', 'quant')).toBe(false)
  expect(canConnect(graph, 'quant', 'review')).toBe(false)
  expect(canConnect({ ...graph, edges: [] }, 'quant', 'risk')).toBe(true)
  const arranged = arrangeGraph(graph)
  expect(arranged.nodes[0].y).toBeLessThan(arranged.nodes[1].y)
  expect(arranged.nodes[1].y).toBeLessThan(arranged.nodes[2].y)
})

it('moves left across the canvas origin and persists negative positions', async () => {
  const fetch = setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  const node = await screen.findByRole('button', { name: 'Select node Quantitative analyst' })
  for (let i = 0; i < 5; i++) fireEvent.keyDown(node, { key: 'ArrowLeft' })
  fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
  await screen.findByText('Draft saved.')
  const saved = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))
  expect(saved.graph.nodes[0].x).toBe(-50)
  expect(saved.graph.nodes[0].y).toBe(50)
  const point = freeNodePosition(graph, { x: -400, y: -200 })
  expect(point).toEqual({ x: -400, y: -200 })
})

function InspectorHarness() {
  const [node, setNode] = useState(graph.nodes[0])
  return <AssistantNodeInspector node={node} graph={graph} readonly={false} onPatch={patch => setNode(n => ({ ...n, ...patch }))} onGraph={vi.fn()} onRemove={vi.fn()} />
}
it('uploads, edits and disables Markdown files without replacing duplicates', async () => {
  render(<InspectorHarness />)
  fireEvent.click(screen.getByRole('tab', { name: /Skills/ }))
  const input = screen.getByLabelText('Upload skill files')
  fireEvent.change(input, { target: { files: [new File(['# Method\nUse cited sources.'], 'SKILL.md', { type: 'text/markdown' })] } })
  const content = await screen.findByLabelText('Skill file content')
  expect(content).toHaveValue('# Method\nUse cited sources.')
  fireEvent.change(content, { target: { value: '# Edited method' } })
  fireEvent.click(screen.getByLabelText('Enabled'))
  expect(screen.getByLabelText('Enabled')).not.toBeChecked()
  fireEvent.change(input, { target: { files: [new File(['Replace'], 'skill.md')] } })
  expect(await screen.findByRole('alert')).toHaveTextContent('Skill filenames must be unique')
  expect(screen.getByLabelText('Skill file content')).toHaveValue('# Edited method')
  fireEvent.change(input, { target: { files: [new File(['x'], 'script.py')] } })
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Upload Markdown files'))
})

it('can undo prompt edits and preserves selection after saving', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: 'Select node Risk reviewer' }))
  fireEvent.change(screen.getByLabelText('Node prompt'), { target: { value: 'Risk method' } })
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  expect(screen.getByLabelText('Node prompt')).toHaveValue('')
  fireEvent.click(screen.getByRole('button', { name: 'Redo' }))
  expect(screen.getByLabelText('Node prompt')).toHaveValue('Risk method')
  fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
  await screen.findByText('Draft saved.')
  expect(screen.getByLabelText('Node name')).toHaveValue('Risk reviewer')
  expect(screen.getByLabelText('Node prompt')).toHaveValue('Risk method')
})

it('starts a version-bound comparison with an explicit virtual-capital action', async () => {
  const fetch = setup()
  render(<AssistantComparison userId="u1" organization={org} current={null} preselected="v1" onCreated={vi.fn()} />, { wrapper: wrapper() })
  expect(await screen.findByText('Election market')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Start comparison with virtual capital' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/paper', expect.objectContaining({ method: 'POST', body: expect.stringContaining('"assistant_version_ids":["v1"]') })))
})

it('shows team responsibilities and real policy, then edits the selected node budget', async () => {
  const fetch = setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('button', { name: 'Configuration' }))
  expect(await screen.findByText('Per-market capital cap')).toBeVisible()
  expect(screen.getByText('6,144')).toBeVisible()
  expect(screen.getByText('Independent analysis')).toBeVisible()
  expect(screen.getByText('ALLOW / REJECT / WAIT with cited reasons')).toBeVisible()
  fireEvent.click(screen.getAllByRole('button', { name: 'Model' })[0])
  const input = await screen.findByLabelText('Node output token limit')
  fireEvent.change(input, { target: { value: '512' } })
  expect(screen.getAllByText('512')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
  await screen.findByText('Draft saved.')
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org1/assistants/a1', expect.objectContaining({ method: 'PUT', body: expect.stringContaining('"max_output_tokens":512') }))
  expect(fetch.mock.calls.some(([path]) => String(path).endsWith('/trial'))).toBe(false)
})

it('blocks invalid node budgets and preserves inherited limits when cleared', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('tab', { name: 'Model' }))
  const input = screen.getByLabelText('Node output token limit')
  fireEvent.change(input, { target: { value: '255' } })
  expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Publish version/ })).toBeDisabled()
  fireEvent.change(input, { target: { value: '' } })
  expect(screen.getByText('4,096')).toBeVisible()
  expect(screen.getByText('2,048')).toBeVisible()
})

it('appends a role-specific method without losing existing instructions and supports undo', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  const prompt = await screen.findByLabelText('Node prompt')
  fireEvent.change(prompt, { target: { value: 'Keep my research focus.' } })
  fireEvent.click(screen.getByText('Role checklist'))
  fireEvent.click(screen.getByRole('button', { name: 'Append checklist to prompt' }))
  expect((prompt as HTMLTextAreaElement).value).toContain('Keep my research focus.')
  expect((prompt as HTMLTextAreaElement).value).toContain('do not recalculate them')
  expect(screen.getByRole('button', { name: 'Append checklist to prompt' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  expect(prompt).toHaveValue('Keep my research focus.')
})

it('keeps model and entry settings read-only for viewers', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={{ ...org, role: 'VIEWER' }} onCompare={vi.fn()} />, { wrapper: wrapper() })
  fireEvent.click(await screen.findByRole('tab', { name: 'Model' }))
  expect(screen.getByLabelText('Node output token limit')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Configuration' }))
  expect(screen.getByLabelText('Minimum 15m movement (pp)')).toBeDisabled()
})

it('lays out both directions without losing configuration and places new nodes without overlap', () => {
  const configured = { ...graph, nodes: graph.nodes.map(n => ({ ...n, prompt: 'Keep my method', skills: [{ name: 'SKILL.md', content: '# Method', enabled: true }] })) }
  for (const direction of ['horizontal', 'vertical'] as const) {
    const arranged = arrangeGraph(configured, direction)
    expect(graphDirection(arranged)).toBe(direction)
    expect(arranged.edges).toEqual(graph.edges)
    expect(arranged.nodes.map(n => ({ ...n, x: 0, y: 0 }))).toEqual(configured.nodes.map(n => ({ ...n, x: 0, y: 0 })))
    const position = freeNodePosition(arranged, arranged.nodes[0])
    expect(arranged.nodes.every(n => Math.abs(n.x - position.x) >= 250 || Math.abs(n.y - position.y) >= 168)).toBe(true)
    expect(position.x).toBeGreaterThanOrEqual(-100000)
    expect(position.x).toBeLessThanOrEqual(100000)
    expect(position.y).toBeGreaterThanOrEqual(-100000)
    expect(position.y).toBeLessThanOrEqual(100000)
  }
})

it('explains broken dependencies and refuses duplicates, cycles and risk bypasses', () => {
  const broken = { ...graph, edges: graph.edges.slice(1) }
  expect(graphIssues(graph)).toEqual([])
  expect(graphIssues(broken)).toEqual([{ nodeId: 'quant', message: 'This analyst has no path to risk review.' }])
  expect(connectionError(graph, 'quant', 'risk')).toBe('These nodes are already connected.')
  expect(connectionError(broken, 'quant', 'review')).toBe('Connect analysts to risk review first.')
  expect(connectionError(graph, 'quant', 'quant')).toBe('A node cannot connect to itself.')
  const branched: AssistantGraph = { ...graph, nodes: [...graph.nodes, { ...graph.nodes[0], id: 'events', kind: 'events' }], edges: [...graph.edges, { source: 'quant', target: 'events' }] }
  expect(connectionError(branched, 'events', 'quant')).toBe('This connection would create a cycle.')
})

it('supports keyboard port connections with useful invalid-target feedback', () => {
  const onChange = vi.fn()
  render(<AssistantCanvas graph={{ ...graph, edges: graph.edges.slice(1) }} onChange={onChange} selected="quant" onSelect={vi.fn()} />)
  fireEvent.keyDown(screen.getByRole('button', { name: 'Connect from Quantitative analyst' }), { key: 'Enter' })
  expect(screen.getByText(/Connecting from Quantitative analyst/)).toBeVisible()
  fireEvent.keyDown(screen.getByRole('button', { name: 'Connect to Entry reviewer' }), { key: 'Enter' })
  expect(screen.getByText('Connect analysts to risk review first.')).toBeVisible()
  expect(onChange).not.toHaveBeenCalled()
  fireEvent.keyDown(screen.getByRole('button', { name: 'Connect to Risk reviewer' }), { key: 'Enter' })
  expect(onChange.mock.lastCall?.[0].edges).toContainEqual({ source: 'quant', target: 'risk' })
  expect(screen.queryByText(/Connecting from Quantitative analyst/)).not.toBeInTheDocument()
})

it('opens the requested editor directly and preserves edits while configuration is hidden', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  fireEvent.change(await screen.findByLabelText('Node prompt'), { target: { value: 'Retain this research method.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Hide configuration' }))
  expect(screen.queryByLabelText('Node prompt')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Edit skills · Quantitative analyst' }))
  expect(screen.getByRole('tab', { name: /Skills/ })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Edit prompt · Quantitative analyst' }))
  expect(screen.getByLabelText('Node prompt')).toHaveValue('Retain this research method.')
})

it('deletes nodes with their connections, restores them with undo, and protects text editing', async () => {
  setup()
  render(<AssistantBuilder userId="u1" organization={org} onCompare={vi.fn()} />, { wrapper: wrapper() })
  const prompt = await screen.findByLabelText('Node prompt')
  fireEvent.change(prompt, { target: { value: 'Keep editing' } })
  fireEvent.keyDown(prompt, { key: 'z', ctrlKey: true })
  fireEvent.keyDown(prompt, { key: 'Delete' })
  expect(prompt).toHaveValue('Keep editing')
  expect(screen.getByRole('button', { name: 'Select node Quantitative analyst' })).toBeInTheDocument()
  fireEvent.keyDown(screen.getByLabelText('Workflow canvas'), { key: 'Delete' })
  expect(screen.queryByRole('button', { name: 'Select node Quantitative analyst' })).not.toBeInTheDocument()
  fireEvent.keyDown(screen.getByLabelText('Workflow canvas'), { key: 'z', ctrlKey: true })
  expect(screen.getByRole('button', { name: 'Select node Quantitative analyst' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Connections ready' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Select node Risk reviewer' }))
  fireEvent.keyDown(screen.getByLabelText('Workflow canvas'), { key: 'Delete' })
  expect(screen.getByText('Required review nodes cannot be removed.')).toBeVisible()
})
