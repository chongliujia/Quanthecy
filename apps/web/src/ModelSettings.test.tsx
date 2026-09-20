import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import ModelSettings from './ModelSettings'
import type { Organization } from './api'

const organization: Organization = { id: 'org1', name: 'Desk', slug: 'desk', kind: 'TEAM', role: 'OWNER' }
const configuration = { revision: 0, provider: 'openai_compatible', base_url: 'https://model.example/v1', model: 'example', has_api_key: false, encryption_available: true, enabled: false, daily_run_limit: 10, max_output_tokens: 2000, context_window_tokens: null, enable_thinking: false, allowed_endpoints: ['https://model.example/v1'] }

function mount(org = organization) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ModelSettings userId="u1" organization={org} /></QueryClientProvider>)
}
it('saves an expanded output budget using the server cap without starting a request', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const saved = init?.method === 'PUT' ? JSON.parse(String(init.body)) : {}
    return new Response(JSON.stringify(String(input).endsWith('/csrf') ? { csrf_token: 'csrf' } : { ...configuration, max_output_tokens_limit: 65536, ...saved }))
  })
  mount()
  const budget = await screen.findByLabelText('Maximum output tokens')
  expect(budget).toHaveAttribute('max', '65536')
  fireEvent.change(budget, { target: { value: '32768' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await screen.findByText('Configuration saved. No model request was made.')
  const sent = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))
  expect(sent.max_output_tokens).toBe(32768)
  expect(sent.max_output_tokens_limit).toBeUndefined()
  expect(fetch.mock.calls.some(([url]) => /\/(test|runs)$/.test(String(url)))).toBe(false)
})

it('saves credentials without sending a test and clears the secret field after saving', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input)
    const data = path.endsWith('/csrf') ? { csrf_token: 'csrf' } : init?.method === 'PUT' ? { ...configuration, revision: 1, has_api_key: true } : configuration
    return new Response(JSON.stringify(data))
  })
  mount()
  fireEvent.change(await screen.findByLabelText('API key'), { target: { value: 'synthetic-secret' } })
  expect(screen.getByRole('button', { name: 'Send test request' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await screen.findByText('Configuration saved. No model request was made.')
  expect(screen.getByLabelText(/^API key/)).toHaveValue('')
  const put = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(put?.[1]?.body)).api_key).toBe('synthetic-secret')
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/test'))).toBe(false)
})
it('prevents viewer configuration access without fetching credentials', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch')
  mount({ ...organization, role: 'VIEWER' })
  expect(screen.getByText(/Ask your workspace owner/)).toBeInTheDocument()
  await waitFor(() => expect(fetch).not.toHaveBeenCalled())
})

it('rechecks encryption availability without losing the model draft', async () => {
  let ready = false
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ ...configuration, encryption_available: ready })))
  mount()
  expect(await screen.findByLabelText('API key')).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Model ID'), { target: { value: 'draft-model' } })
  ready = true
  fireEvent.click(screen.getByRole('button', { name: 'Recheck credential storage' }))
  await waitFor(() => expect(screen.getByLabelText('API key')).toBeEnabled())
  expect(screen.getByLabelText('Model ID')).toHaveValue('draft-model')
})

it('changes protocol without offering the previous connection key to the new provider', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => new Response(JSON.stringify(String(input).endsWith('/csrf') ? { csrf_token: 'csrf' } : init?.method === 'PUT' ? { ...configuration, revision: 1 } : { ...configuration, has_api_key: true, allowed_endpoints: [...configuration.allowed_endpoints, 'https://api.anthropic.com/v1'] })))
  mount()
  fireEvent.change(await screen.findByLabelText('Model provider'), { target: { value: 'anthropic' } })
  expect(screen.getByLabelText('API base URL')).toHaveValue('https://api.anthropic.com/v1')
  expect(screen.getByRole('button', { name: 'Save configuration' })).toBeEnabled()
  expect(screen.queryByLabelText('Remove saved API key')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/^API key/), { target: { value: 'new-provider-test-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await screen.findByText('Configuration saved. No model request was made.')
  const sent = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))
  expect(sent).toMatchObject({ provider: 'anthropic', clear_api_key: false, enabled: false })
  expect(sent.api_key).toBe('new-provider-test-key')
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/test'))).toBe(false)
})

it('saves a local model without a key or implicit inference and persists its options', async () => {
  const initial = { ...configuration, encryption_available: false, allowed_endpoints: [...configuration.allowed_endpoints, 'http://127.0.0.1:8001/v1'] }
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const saved = init?.method === 'PUT' ? JSON.parse(String(init.body)) : {}
    return new Response(JSON.stringify(String(input).endsWith('/csrf') ? { csrf_token: 'csrf' } : { ...initial, ...saved }))
  })
  mount()
  fireEvent.change(await screen.findByLabelText('Model provider'), { target: { value: 'local' } })
  expect(screen.getByLabelText('API base URL')).toHaveValue('http://127.0.0.1:8001/v1')
  expect(screen.getByLabelText('Provider protocol')).toHaveValue('local')
  expect(screen.getByLabelText('Context window tokens')).toHaveValue(8192)
  expect(screen.getByLabelText('Enable thinking mode')).not.toBeChecked()
  fireEvent.change(screen.getByLabelText('Model ID'), { target: { value: 'offline-model' } })
  fireEvent.click(screen.getByRole('switch'))
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await screen.findByText('Configuration saved. No model request was made.')
  const sent = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))
  expect(sent).toMatchObject({ provider: 'local', model: 'offline-model', context_window_tokens: 8192, enable_thinking: false, enabled: true })
  expect(sent.api_key).toBeUndefined()
  expect(fetch.mock.calls.some(([url]) => /\/(test|runs)$/.test(String(url)))).toBe(false)
})

it('blocks an output budget that consumes the entire local context window', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ...configuration, provider: 'local', base_url: 'http://127.0.0.1:8001/v1', context_window_tokens: 8192, allowed_endpoints: ['http://127.0.0.1:8001/v1'] })))
  mount()
  expect(await screen.findByLabelText('Model provider')).toHaveValue('local')
  fireEvent.change(screen.getByLabelText('Maximum output tokens'), { target: { value: '8192' } })
  expect(screen.getByRole('alert')).toHaveTextContent('Set the local model context window above the maximum output tokens.')
  expect(screen.getByRole('button', { name: 'Save configuration' })).toBeDisabled()
})

it('allows a keyless local connection without asking to delete the cloud credential', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ...configuration, has_api_key: true, allowed_endpoints: [...configuration.allowed_endpoints, 'http://127.0.0.1:8001/v1'] })))
  mount()
  fireEvent.change(await screen.findByLabelText('Model provider'), { target: { value: 'local' } })
  fireEvent.change(screen.getByLabelText('Model ID'), { target: { value: 'offline-model' } })
  expect(screen.getByRole('button', { name: 'Save configuration' })).toBeEnabled()
  expect(screen.queryByLabelText('Remove saved API key')).not.toBeInTheDocument()
})

it('restores a saved cloud connection after local use without requesting its key again', async () => {
  const cloud = { id: 'cloud1', provider: 'openai_compatible', base_url: 'https://api.deepseek.com', model: 'saved-cloud-model', has_api_key: true, max_output_tokens: 32768, context_window_tokens: null, enable_thinking: false }
  const local = { id: 'local1', provider: 'local', base_url: 'http://127.0.0.1:8001/v1', model: 'offline-model', has_api_key: false, max_output_tokens: 1024, context_window_tokens: 8192, enable_thinking: false }
  const initial = { ...configuration, ...local, enabled: true, revision: 2, allowed_endpoints: [cloud.base_url, local.base_url], connections: [local, cloud] }
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => new Response(JSON.stringify(String(input).endsWith('/csrf') ? { csrf_token: 'csrf' } : init?.method === 'PUT' ? { ...initial, ...cloud, revision: 3 } : initial)))
  mount()
  fireEvent.change(await screen.findByLabelText('Saved connections'), { target: { value: 'cloud1' } })
  expect(screen.getByLabelText('Model ID')).toHaveValue('saved-cloud-model')
  expect(screen.getByLabelText('Maximum output tokens')).toHaveValue(32768)
  expect(screen.getByLabelText(/^API key/)).toHaveValue('')
  expect(screen.getByPlaceholderText('Leave blank to keep the saved key')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Save configuration' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await screen.findByText('Configuration saved. No model request was made.')
  const sent = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))
  expect(sent).toMatchObject({ revision: 2, base_url: cloud.base_url, model: cloud.model, clear_api_key: false })
  expect(sent.api_key).toBeUndefined()
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/test'))).toBe(false)
})

it('restores the current cloud settings when switching back before saving local changes', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ...configuration, provider: 'openai', base_url: 'https://api.openai.com/v1', model: 'saved-model', has_api_key: true, max_output_tokens: 32768, allowed_endpoints: ['https://api.openai.com/v1', 'http://127.0.0.1:8001/v1'] })))
  mount()
  fireEvent.change(await screen.findByLabelText('Model provider'), { target: { value: 'local' } })
  fireEvent.change(screen.getByLabelText('Model provider'), { target: { value: 'openai' } })
  expect(screen.getByLabelText('Model ID')).toHaveValue('saved-model')
  expect(screen.getByLabelText('Maximum output tokens')).toHaveValue(32768)
  expect(screen.getByPlaceholderText('Leave blank to keep the saved key')).toBeVisible()
})
