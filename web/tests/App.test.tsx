import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../src/App'

function renderApp() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('session loading is announced instead of showing a blank screen', () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>(() => {})),
  )
  renderApp()
  expect(screen.getByRole('status')).toHaveTextContent('Loading Iris')
  expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
})

test('a server failure offers retry rather than asking the user to sign in again', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ detail: 'Server failure' }, { status: 500 })),
  )
  renderApp()
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your session')
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
})

test.each([false, true])(
  'successful login replaces the login screen (2FA=%s)',
  async (twoFactor) => {
    let authenticated = false
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/auth/options') return Response.json({ two_factor_enabled: twoFactor })
        if (url === '/api/auth/login') {
          if (twoFactor) return Response.json({ challenge_id: 'challenge' })
          authenticated = true
          return Response.json({ username: 'admin' })
        }
        if (url === '/api/auth/verify') {
          authenticated = true
          return Response.json({ username: 'admin' })
        }
        if (url === '/api/auth/me')
          return authenticated
            ? Response.json({ id: 1, username: 'admin', role: 'admin' })
            : Response.json({ detail: 'Not authenticated' }, { status: 401 })
        if (url === '/api/auth/phones' || url === '/api/chats') return Response.json([])
        if (url === '/api/version') return Response.json({ version: 'test' })
        if (url.startsWith('/api/stats'))
          return Response.json({
            messages_today: 0,
            messages_7d: 0,
            alerts_by_status: {},
            alerts_by_delivery: {},
            review_queue: 0,
            jobs_by_status: {},
            queue_depth: 0,
            failed_jobs: 0,
            delivery_configured: false,
            instances: 0,
            silent_instances: 0,
          })
        return Response.json({ items: [] })
      }),
    )
    renderApp()
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    if (twoFactor) {
      fireEvent.change(await screen.findByLabelText('Verification code'), {
        target: { value: '123456' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'Verify code' }))
    }
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument(),
    )
    expect(await screen.findByRole('link', { name: 'Home' })).toBeInTheDocument()
  },
)
