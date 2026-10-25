export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function errorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail.replace(/^Value error, /, '')
  if (Array.isArray(detail)) return detail.map(errorDetail).filter(Boolean).join('; ')
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    if (typeof value.msg === 'string') {
      const location = Array.isArray(value.loc)
        ? value.loc.filter((v) => v !== 'body').join('.')
        : ''
      return `${location ? location + ': ' : ''}${errorDetail(value.msg)}`
    }
    return Object.entries(value)
      .map(([key, message]) => `${key}: ${errorDetail(message)}`)
      .join('; ')
  }
  return ''
}

export const REQUEST_TIMEOUT_MS = 30_000
let pending = 0
const listeners = new Set<() => void>()
export const requestActivity = {
  subscribe: (listener: () => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },
  snapshot: () => pending,
}
function activity(delta: number) {
  pending += delta
  listeners.forEach((listener) => listener())
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout =
    path === '/api/database/copy'
      ? 300_000
      : path.includes('/original') || path.includes('/test') || path.includes('/classify')
        ? 120_000
        : REQUEST_TIMEOUT_MS
  let timer: ReturnType<typeof setTimeout>
  const abort = () => controller.abort(init?.signal?.reason)
  init?.signal?.addEventListener('abort', abort, { once: true })
  if (init?.signal?.aborted) abort()
  activity(1)
  try {
    // Race also bounds response-body parsing and transports that ignore cancellation.
    return await Promise.race([
      (async () => {
        const res = await fetch(path, {
          ...init,
          signal: controller.signal,
          headers: { 'Content-Type': 'application/json', ...init?.headers },
          credentials: 'same-origin',
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new ApiError(
            res.status,
            errorDetail(body.detail) || res.statusText || `Request failed (HTTP ${res.status}).`,
          )
        }
        if (res.status === 204 || res.status === 205) return undefined as T
        return (await res.json()) as T
      })(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => {
          reject(
            new ApiError(408, 'Iris took too long to respond. Check the result, then try again.'),
          )
          controller.abort()
        }, timeout)
      }),
    ])
  } finally {
    clearTimeout(timer!)
    init?.signal?.removeEventListener('abort', abort)
    activity(-1)
  }
}
