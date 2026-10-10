import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Jobs } from '../../src/pages/Jobs'

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
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(calls).toContain('POST /api/jobs/7/retry')
})

test('queued jobs show their next attempt and do not offer a duplicate retry', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.includes('status=queued')
          ? [
              {
                id: 8,
                type: 'test_alert',
                status: 'queued',
                attempts: 0,
                max_attempts: 3,
                last_error: 'Waiting for sending capacity',
                message_id: null,
                created_at: '2026-10-09T10:00:00Z',
                run_after: '2026-10-09T10:01:00Z',
              },
            ]
          : [],
      ),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Jobs />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Job status' }), 'queued')
  expect(await screen.findByText('Sending a test alert')).toBeInTheDocument()
  expect(screen.getByText(/Next attempt:/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
})
