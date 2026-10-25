import { renderWithApp } from '../test-utils'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Login } from '../../src/pages/Login'

function renderLogin(status: number) {
  const calls: { url: string; body?: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined })
      return new Response(
        JSON.stringify(status === 200 ? { username: 'admin' } : { detail: 'x' }),
        { status },
      )
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Login />
    </QueryClientProvider>,
  )
  return calls
}

async function fillAndSubmit() {
  await userEvent.type(screen.getByLabelText('Username'), 'admin')
  await userEvent.type(screen.getByLabelText('Password'), 'secret-pass')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

test('submitting the form signs in with the typed credentials', async () => {
  const calls = renderLogin(200)
  await fillAndSubmit()
  const post = calls.find((c) => c.url === '/api/auth/login')
  expect(JSON.parse(post!.body!)).toEqual({
    username: 'admin',
    password: 'secret-pass',
  })
})

test('pressing Enter in the password field also submits', async () => {
  const calls = renderLogin(200)
  await userEvent.type(screen.getByLabelText('Username'), 'admin')
  await userEvent.type(screen.getByLabelText('Password'), 'secret-pass{Enter}')
  expect(calls.some((c) => c.url === '/api/auth/login')).toBe(true)
})

test('explains a wrong password and a lockout in plain words', async () => {
  renderLogin(401)
  await fillAndSubmit()
  expect(await screen.findByRole('alert')).toHaveTextContent(/username and password do not match/)
})

test('explains a lockout after too many attempts', async () => {
  renderLogin(429)
  await fillAndSubmit()
  expect(await screen.findByRole('alert')).toHaveTextContent(/Wait a few minutes/)
})

test('duplicate submits cannot consume an OTP twice when the session cookie is rejected', async () => {
  renderWithApp(<Login />, {})
  let verifyCalls = 0
  let complete: (value: Response) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/options') return Response.json({ two_factor_enabled: true })
      if (url === '/api/auth/login') return Response.json({ challenge_id: 'challenge' })
      if (url === '/api/auth/verify') {
        verifyCalls++
        return new Promise<Response>((resolve) => {
          complete = resolve
        })
      }
      return Response.json({ detail: 'Not authenticated' }, { status: 401 })
    }),
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  const input = await screen.findByLabelText('Verification code')
  fireEvent.change(input, { target: { value: '123456' } })
  const form = input.closest('form')!
  fireEvent.submit(form)
  fireEvent.submit(form)
  expect(verifyCalls).toBe(1)
  complete(Response.json({ username: 'admin' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('code was accepted'))
  fireEvent.submit(form)
  expect(verifyCalls).toBe(1)
  await userEvent.click(screen.getByRole('button', { name: /Start again/ }))
  expect(screen.getByLabelText('Username')).toBeInTheDocument()
})

test('a missing approved contact shows the server explanation for 403', async () => {
  renderWithApp(<Login />, {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/options') return Response.json({ two_factor_enabled: true })
      return Response.json({ detail: 'No approved contact is available for 2FA' }, { status: 403 })
    }),
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'parent' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'No approved contact is available for 2FA',
  )
})

test('HTTP login directs the user to the configured HTTPS address', async () => {
  renderWithApp(<Login />, {
    '/api/auth/options': {
      two_factor_enabled: true,
      secure_login_url: 'https://iris.example.com/',
    },
  })
  expect(await screen.findByRole('link', { name: 'Open secure Iris' })).toHaveAttribute(
    'href',
    'https://iris.example.com/',
  )
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
})

test('pasted spaced codes are submitted as six digits', async () => {
  const calls = renderWithApp(<Login />, {
    '/api/auth/options': { two_factor_enabled: true },
    '/api/auth/login': { challenge_id: 'challenge' },
  })
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  const input = await screen.findByLabelText('Verification code')
  fireEvent.paste(input, { clipboardData: { getData: () => '\u200e1 2 3 4 5 6\u200f' } })
  expect(input).toHaveValue('123456')
  fireEvent.click(screen.getByRole('button', { name: 'Verify code' }))
  await waitFor(() =>
    expect(
      calls.some((c) => c.url === '/api/auth/verify' && JSON.stringify(c.body).includes('123456')),
    ).toBe(true),
  )
})

test('login shows progress, times out and allows another attempt', async () => {
  renderWithApp(<Login />, {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/options') return Response.json({ two_factor_enabled: false })
      return new Promise<Response>(() => {})
    }),
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  vi.useFakeTimers()
  try {
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByRole('progressbar', { name: 'Sign-in progress' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(screen.getByRole('alert')).toHaveTextContent('took too long')
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
  } finally {
    vi.useRealTimers()
  }
})

test('retrying session loading never resubmits an accepted verification code', async () => {
  renderWithApp(<Login />, {})
  let verificationCalls = 0
  let sessionCalls = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/options') return Response.json({ two_factor_enabled: true })
      if (url === '/api/auth/login') return Response.json({ challenge_id: 'challenge' })
      if (url === '/api/auth/verify') {
        verificationCalls++
        return Response.json({ ok: true })
      }
      if (url === '/api/auth/me') {
        sessionCalls++
        if (sessionCalls === 1) throw new Error('Connection interrupted')
        return Response.json({ username: 'admin', role: 'admin' })
      }
      return Response.json({})
    }),
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  fireEvent.change(await screen.findByLabelText('Verification code'), {
    target: { value: '123456' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Verify code' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Retry session' }))
  await waitFor(() => expect(sessionCalls).toBe(2))
  expect(verificationCalls).toBe(1)
})

test('timed-out verification offers session recovery instead of replaying its code', async () => {
  renderWithApp(<Login />, {})
  let verificationCalls = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/options') return Response.json({ two_factor_enabled: true })
      if (url === '/api/auth/login') return Response.json({ challenge_id: 'challenge' })
      if (url === '/api/auth/verify') {
        verificationCalls++
        return new Promise<Response>(() => {})
      }
      return Response.json({ username: 'admin', role: 'admin' })
    }),
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  fireEvent.change(await screen.findByLabelText('Verification code'), {
    target: { value: '123456' },
  })
  vi.useFakeTimers()
  try {
    fireEvent.click(screen.getByRole('button', { name: 'Verify code' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(screen.getByRole('alert')).toHaveTextContent('Verification timed out')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry session' }))
    })
    expect(verificationCalls).toBe(1)
  } finally {
    vi.useRealTimers()
  }
})

test('WhatsApp pacing shows the retry delay and email alternative', async () => {
  renderWithApp(<Login />, {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/api/auth/options'
        ? Response.json({ two_factor_enabled: true })
        : Response.json(
            { detail: 'WhatsApp code limit reached. Retry in 60 seconds, or use email.' },
            { status: 429 },
          ),
    ),
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Retry in 60 seconds, or use email')
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
})
