import { describe, expect, it, vi } from 'vitest'
import { api } from './api'

describe('session API', () => {
  it('obtains a fresh CSRF token before a state-changing request', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: 'fresh-token' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'ok' })))
    await api('/auth/logout', 'POST')
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/v1/auth/logout', expect.objectContaining({
      credentials: 'same-origin', headers: expect.objectContaining({ 'X-CSRFToken': 'fresh-token' }),
    }))
  })
  it('does not submit a mutation when CSRF retrieval fails', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('unavailable', { status: 503 }))
    await expect(api('/auth/register', 'POST', {})).rejects.toMatchObject({ status: 503 })
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
