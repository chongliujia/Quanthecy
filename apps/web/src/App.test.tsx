import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import App from './App'

function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider>)
}

function researchResponse(path: string) {
  if (path.endsWith('/research/overview')) return { markets: 0, fresh_markets: 0, reviewed_pairs: 0, evidence_items: 0, latest_observation: null, sources: [], news_polling_enabled: true }
  if (path.endsWith('/comparisons')) return []
  if (path.includes('/evidence?')) return { items: [], total: 0 }
  if (path.includes('/markets?')) return { items: [], total: 0 }
  return undefined
}

it('shows a recoverable connection error instead of the login form for an unavailable API', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Connection unavailable'))
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach your workspace')
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
})

it('shows login for an anonymous session and allows switching to registration', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 }))
  mount()
  expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'New to Quanthecy? Create an account' }))
  expect(screen.getByRole('heading', { name: 'Create your workspace' })).toBeInTheDocument()
})

it('switches languages without clearing input and remembers the selection', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 401 }))
  mount()
  fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'draft@example.test' } })
  fireEvent.click(screen.getByRole('button', { name: '中文' }))
  expect(screen.getByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
  expect(screen.getByLabelText('邮箱')).toHaveValue('draft@example.test')
  expect(document.documentElement.lang).toBe('zh-CN')
  expect(localStorage.getItem('quanthecy.language')).toBe('zh')
  fireEvent.click(screen.getByRole('button', { name: 'English' }))
  expect(screen.getByLabelText('Email')).toHaveValue('draft@example.test')
  expect(document.documentElement.lang).toBe('en')
})

it('changes theme without losing login input or language', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  mount()
  fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'draft@example.test' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Color theme' }), { target: { value: 'light' } })
  expect(document.documentElement.dataset.theme).toBe('light')
  fireEvent.click(screen.getByRole('button', { name: '中文' }))
  fireEvent.change(screen.getByRole('combobox', { name: '颜色主题' }), { target: { value: 'dark' } })
  expect(screen.getByLabelText('邮箱')).toHaveValue('draft@example.test')
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(document.documentElement.lang).toBe('zh-CN')
})

it('opens the workspace after login and removes private views on logout', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    if (path.endsWith('/me')) return new Response('{}', { status: 401 })
    const body = researchResponse(path) ?? (path.endsWith('/csrf') ? { csrf_token: 'csrf' }
      : path.endsWith('/login') ? { id: 'u1', email: 'owner@example.com', email_verified_at: null }
        : path.endsWith('/logout') ? { detail: 'Signed out' }
          : path.includes('/organizations?') ? [{ id: 'org1', name: 'Private workspace', role: 'OWNER' }]
            : [{ id: 'm1', user_id: 'u1', email: 'owner@example.com', role: 'OWNER' }])
    return new Response(JSON.stringify(body))
  })
  mount()
  fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'owner@example.com' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('heading', { name: 'Research overview' })).toBeInTheDocument()
  expect(await screen.findByRole('option', { name: 'Private workspace' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
  expect(screen.queryByRole('option', { name: 'Private workspace' })).not.toBeInTheDocument()
})

it('loads members within the selected workspace without retaining the previous member list', async () => {
  window.history.replaceState(null, '', '/#/workspace')
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input)
    const body = researchResponse(path) ?? (path.endsWith('/me') ? { id: 'u1', email: 'owner@example.com', email_verified_at: null }
      : path.includes('/organizations?') ? [{ id: 'org1', name: 'First', role: 'OWNER' }, { id: 'org2', name: 'Second', role: 'VIEWER' }]
        : path.includes('/org1/members') ? [{ id: 'm1', user_id: 'u1', email: 'first@example.com', role: 'OWNER' }]
          : [{ id: 'm2', user_id: 'u2', email: 'second@example.com', role: 'MEMBER' }])
    return new Response(JSON.stringify(body))
  })
  mount()
  expect(await screen.findByText('first@example.com')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Active workspace'), { target: { value: 'org2' } })
  expect(await screen.findByText('second@example.com')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText('first@example.com')).not.toBeInTheDocument())
  expect(fetch).toHaveBeenCalledWith('/api/v1/organizations/org2/members?limit=100', expect.anything())
})
