import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import ModelSettings from './ModelSettings'
import type { Organization } from './api'

const organization: Organization = { id: 'org1', name: 'Desk', slug: 'desk', kind: 'TEAM', role: 'OWNER' }
const configuration = { revision: 0, provider: 'openai_compatible', base_url: 'https://model.example/v1', model: 'example', has_api_key: false, encryption_available: true, enabled: false, daily_run_limit: 10, max_output_tokens: 2000, allowed_endpoints: ['https://model.example/v1'] }

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

it('changes protocol and requires an explicit replacement for the old credential', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => new Response(JSON.stringify(String(input).endsWith('/csrf') ? { csrf_token: 'csrf' } : init?.method === 'PUT' ? { ...configuration, revision: 1 } : { ...configuration, has_api_key: true, allowed_endpoints: [...configuration.allowed_endpoints, 'https://api.anthropic.com/v1'] })))
  mount()
  fireEvent.change(await screen.findByLabelText('Model provider'), { target: { value: 'anthropic' } })
  expect(screen.getByLabelText('API base URL')).toHaveValue('https://api.anthropic.com/v1')
  expect(screen.getByRole('button', { name: 'Save configuration' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/^API key/), { target: { value: 'new-provider-test-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await screen.findByText('Configuration saved. No model request was made.')
  const sent = JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))
  expect(sent).toMatchObject({ provider: 'anthropic', clear_api_key: false, enabled: false })
  expect(sent.api_key).toBe('new-provider-test-key')
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/test'))).toBe(false)
})
