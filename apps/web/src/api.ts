export interface User { id: string; email: string; email_verified_at: string | null }
export interface Organization { id: string; name: string; slug: string; kind: string; role: string }
export interface Member { id: string; user_id: string; email: string; role: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail
      : Array.isArray(body.detail) && body.detail.every((item: unknown) => typeof item === 'string')
        ? body.detail.join(' ') : 'The request could not be completed. Please try again.'
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') {
    const csrf = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
    const { csrf_token } = await decode<{ csrf_token: string }>(csrf)
    headers['X-CSRFToken'] = csrf_token
    headers['Content-Type'] = 'application/json'
  }
  return decode<T>(await fetch(`/api/v1${path}`, {
    method, credentials: 'same-origin', cache: 'no-store', headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }))
}
