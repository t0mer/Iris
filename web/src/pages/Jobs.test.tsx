import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Jobs } from './Jobs'

test('lists failed jobs with their error and retries one', async () => {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      const body =
        url === '/api/jobs'
          ? [
              {
                id: 7,
                type: 'process_message',
                status: 'failed',
                attempts: 1,
                max_attempts: 5,
                last_error: 'OpenWA has no stored media',
                message_id: 3,
                created_at: '2026-10-06T10:00:00Z',
              },
            ]
          : { ok: true }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Jobs />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText(/OpenWA has no stored media/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'ניסיון נוסף' }))
  expect(calls).toContain('POST /api/jobs/7/retry')
})
