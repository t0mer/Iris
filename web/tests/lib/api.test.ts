import { api, ApiError, REQUEST_TIMEOUT_MS, requestActivity } from '../../src/lib/api'

test('successful deletion with no content resolves without parsing JSON', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(null, { status: 204 })),
  )
  await expect(api('/api/instances/1', { method: 'DELETE' })).resolves.toBeUndefined()
})

test('JSON responses still return their body', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ id: 1 }), { status: 200 })),
  )
  await expect(api('/api/instances/1')).resolves.toEqual({ id: 1 })
})

test('failed deletion remains an API error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'Phone not found' }), { status: 404 })),
  )
  await expect(api('/api/instances/1', { method: 'DELETE' })).rejects.toBeInstanceOf(ApiError)
})

test('validation errors show their field and message instead of object coercion', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ['body', 'email'],
                msg: 'Value error, Enter a valid email address',
                input: 'invalid',
              },
            ],
          }),
          { status: 422 },
        ),
    ),
  )
  await expect(api('/api/users', { method: 'POST' })).rejects.toThrow(
    'email: Enter a valid email address',
  )
})

test('hung requests time out, abort transport and release progress for retry', async () => {
  vi.useFakeTimers()
  try {
    let signal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((_path: string, init?: RequestInit) => {
        signal = init?.signal as AbortSignal
        return new Promise<Response>(() => {})
      }),
    )
    const result = api('/api/auth/login', { method: 'POST' })
    const rejected = expect(result).rejects.toMatchObject({ status: 408 })
    expect(requestActivity.snapshot()).toBe(1)
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    await rejected
    expect(signal?.aborted).toBe(true)
    expect(requestActivity.snapshot()).toBe(0)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ ok: true })),
    )
    await expect(api('/api/auth/login', { method: 'POST' })).resolves.toEqual({ ok: true })
  } finally {
    vi.useRealTimers()
  }
})

test('timeout also bounds reading a stalled response body', async () => {
  vi.useFakeTimers()
  try {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: () => new Promise(() => {}) })),
    )
    const rejected = expect(api('/api/settings')).rejects.toMatchObject({ status: 408 })
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    await rejected
    expect(requestActivity.snapshot()).toBe(0)
  } finally {
    vi.useRealTimers()
  }
})
