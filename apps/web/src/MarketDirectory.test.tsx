import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import MarketDirectory from './MarketDirectory'

function mount(onOpen = vi.fn()) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MarketDirectory userId="u1" onOpen={onOpen} /></QueryClientProvider>)
  return onOpen
}
const row = { id: 'c1', platform: 'polymarket', exchange_id: '123', title: 'A discovered question', status: 'OPEN', volume_24h: null, volume_unit: 'USD', last_seen_at: '2026-09-17T00:00:00Z', stale: true, collection: 'directory', has_history: false }
it('does not fabricate prices or allow opening a terminal without observations', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ items: [row], total: 1 })))
  const open = mount()
  expect(await screen.findByText(row.title)).toBeInTheDocument()
  expect(screen.getByText('Directory only')).toBeInTheDocument()
  expect(screen.getByText('Price history not collected yet')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: row.title })).not.toBeInTheDocument()
  expect(open).not.toHaveBeenCalled()
})
it('opens saved history and resets pagination when exchange changes', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ items: [{ ...row, collection: 'standard', has_history: true }], total: 21 })))
  const open = mount()
  fireEvent.click(await screen.findByRole('button', { name: row.title }))
  expect(open).toHaveBeenCalledWith('c1')
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByText('21–21 of 21')
  fireEvent.change(screen.getByLabelText('Platform'), { target: { value: 'kalshi' } })
  await screen.findByText('1–20 of 21')
  expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('offset=0&platform=kalshi'), expect.anything())
})
it('shows retry without converting a request failure into an empty directory', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Unavailable'))
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('Market directory is unavailable.')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})
