import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PhonePairing } from '../../src/components/PhonePairing'

const qr = 'data:image/png;base64,iVBORw0KGgo='
function setup() {
  const calls: { url: string; method: string }[] = []
  const onChange = vi.fn()
  const savedToken = { current: null as string | null }
  const data = { status: 'qr_ready', qr, session_id: 'draft-id', qr_valid_seconds: 45 }
  let fail = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method || 'GET' })
      if (init?.method === 'DELETE') return new Response(null, { status: 204 })
      if (fail)
        return new Response(JSON.stringify({ detail: 'OpenWA unavailable' }), { status: 502 })
      return new Response(
        JSON.stringify(
          url === '/api/pairing'
            ? { token: 'draft-token', session_id: 'draft-id', status: 'waiting', qr: null }
            : url.endsWith('/refresh')
              ? { ...data, qr: null, status: 'waiting' }
              : data,
        ),
      )
    }),
  )
  const rendered = render(
    <PhonePairing
      url="https://wa.example"
      apiKey="example-key"
      onChange={onChange}
      savedToken={savedToken}
    />,
  )
  return {
    calls,
    onChange,
    savedToken,
    rendered,
    data,
    setFail: () => {
      fail = true
    },
  }
}

test('shows QR before other form fields exist and unregisters on exit', async () => {
  const { calls, rendered } = setup()
  await userEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
  expect(await screen.findByRole('img', { name: 'WhatsApp pairing QR code' })).toHaveAttribute(
    'src',
    qr,
  )
  rendered.unmount()
  expect(calls).toContainEqual({ url: '/api/pairing/draft-token', method: 'DELETE' })
})

test('manual refresh clears old QR and requests a new code', async () => {
  const { calls } = setup()
  await userEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
  await screen.findByRole('img')
  await userEvent.click(screen.getByRole('button', { name: 'Refresh QR' }))
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(calls).toContainEqual({ url: '/api/pairing/draft-token/refresh', method: 'POST' })
})

test('polling keeps the current OpenWA QR without restarting at 45 seconds', async () => {
  vi.useFakeTimers()
  try {
    const { calls } = setup()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByRole('img')).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(45000)
    })
    expect(calls).not.toContainEqual({ url: '/api/pairing/draft-token/refresh', method: 'POST' })
    expect(screen.getByRole('img')).toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

test('a failed OpenWA connection never shows QR', async () => {
  const { setFail } = setup()
  setFail()
  await userEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('OpenWA unavailable')
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

test('polling errors remove a previously displayed QR', async () => {
  vi.useFakeTimers()
  try {
    const { setFail } = setup()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByRole('img')).toBeInTheDocument()
    setFail()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('OpenWA unavailable')
  } finally {
    vi.useRealTimers()
  }
})

test('saved sessions are retained when form closes', async () => {
  const { calls, savedToken, rendered } = setup()
  await userEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
  await screen.findByRole('img')
  savedToken.current = 'draft-token'
  rendered.unmount()
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
})

test('undisplayable QR triggers automatic regeneration', async () => {
  const { calls } = setup()
  await userEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
  fireEvent.error(await screen.findByRole('img'))
  await waitFor(() =>
    expect(calls).toContainEqual({ url: '/api/pairing/draft-token/refresh', method: 'POST' }),
  )
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

test('starting a slow session immediately shows activity and feedback', async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve
        }),
    ),
  )
  render(<PhonePairing name="" onChange={vi.fn()} savedToken={{ current: null }} />)
  await userEvent.click(screen.getByRole('button', { name: 'Get pairing QR' }))
  expect(screen.getByRole('status')).toHaveTextContent('Pairing started')
  expect(
    screen.getByRole('progressbar', { name: 'Waiting for WhatsApp pairing' }),
  ).toBeInTheDocument()
  expect(screen.getByText(/Elapsed: 0s/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Connecting to OpenWA…' })).toBeDisabled()
  await act(async () =>
    finish(new Response(JSON.stringify({ detail: 'OpenWA unavailable' }), { status: 502 })),
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('OpenWA unavailable')
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})
