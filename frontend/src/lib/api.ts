/**
 * api.ts — HTTP + SSE client with automatic access-token refresh.
 */

const BASE = ''

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

const tokens = {
  get access() { return localStorage.getItem('mizan_access') || '' },
  get refresh() { return localStorage.getItem('mizan_refresh') || '' },
  set(access: string, refresh: string) {
    localStorage.setItem('mizan_access', access)
    localStorage.setItem('mizan_refresh', refresh)
  },
  clear() {
    localStorage.removeItem('mizan_access')
    localStorage.removeItem('mizan_refresh')
  },
}

export { tokens }

let refreshPromise: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    try {
      const r = await fetch(`${BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: tokens.refresh }),
      })
      if (!r.ok) return false
      const data = await r.json()
      tokens.set(data.access_token, data.refresh_token)
      return true
    } catch {
      return false
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
  retried = false,
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  }
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`

  const res = await fetch(`${BASE}${path}`, { ...options, headers })

  if (res.status === 401 && !retried && tokens.refresh) {
    const ok = await tryRefresh()
    if (ok) return api<T>(path, options, true)
    tokens.clear()
  }

  if (!res.ok) {
    let code = 'http_error'
    let message = `خطأ ${res.status}`
    try {
      const body = await res.json()
      if (body?.error) {
        code = body.error.code
        message = body.error.message
      }
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, code, message)
  }
  return res.json() as Promise<T>
}

// ─── SSE streaming chat ───────────────────────────────────────────────────────
export interface StreamCallbacks {
  onMeta?: (data: { conversation_id: string; user_message_id: number }) => void
  onToken?: (token: string) => void
  onDone?: (data: Record<string, unknown>) => void
  onError?: (message: string) => void
}

export async function streamChat(
  body: Record<string, unknown>,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const doFetch = () =>
    fetch(`${BASE}/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${tokens.access}`,
      },
      body: JSON.stringify(body),
      signal,
    })

  let res = await doFetch()
  if (res.status === 401 && (await tryRefresh())) {
    res = await doFetch()
  }
  if (!res.ok || !res.body) {
    let message = `خطأ ${res.status}`
    try {
      const j = await res.json()
      message = j?.error?.message || message
    } catch { /* ignore */ }
    callbacks.onError?.(message)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      let event = 'message'
      let data = ''
      for (const line of part.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim()
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (!data) continue
      try {
        const payload = JSON.parse(data)
        if (event === 'meta') callbacks.onMeta?.(payload)
        else if (event === 'token') callbacks.onToken?.(payload.t)
        else if (event === 'done') callbacks.onDone?.(payload)
        else if (event === 'error') callbacks.onError?.(payload.message || 'خطأ غير معروف')
      } catch { /* skip malformed */ }
    }
  }
}
