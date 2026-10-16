import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'

test('shows login when unauthenticated', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{"detail":"no"}', { status: 401 })),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('button', { name: 'כניסה' })).toBeInTheDocument()
})
