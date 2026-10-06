import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Login } from './Login'

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
  expect(JSON.parse(post!.body!)).toEqual({ username: 'admin', password: 'secret-pass' })
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
