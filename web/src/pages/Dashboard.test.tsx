import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Dashboard } from './Dashboard'

const stats: Record<string, unknown> = {
  messages_today: 12,
  messages_7d: 80,
  alerts_by_status: { new: 3 },
  alerts_by_delivery: { failed: 1 },
  review_queue: 2,
  jobs_by_status: {},
  queue_depth: 0,
  failed_jobs: 4,
  delivery_configured: false,
  instances: 2,
  silent_instances: 1,
}

function renderPage(over: Record<string, unknown> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(url.startsWith('/api/stats') ? { ...stats, ...over } : { items: [] }),
          { status: 200 },
        ),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('shows the numbers and names everything that needs attention', async () => {
  renderPage()
  expect(await screen.findByText('12')).toBeInTheDocument()
  expect(screen.getByText('80')).toBeInTheDocument()
  const list = within(await screen.findByRole('region', { name: 'Needs attention' }))
  expect(list.getByText(/Alert delivery is not configured/)).toBeInTheDocument()
  expect(list.getByText('4 jobs failed')).toBeInTheDocument()
  expect(list.getByText(/never received a webhook/)).toBeInTheDocument()
  expect(list.getByText(/3 new alerts to read/)).toBeInTheDocument()
  expect(list.getByText(/2 messages Iris could not decide/)).toBeInTheDocument()
  expect(screen.getByText('3 alerts and 2 to review need you')).toBeInTheDocument()
})

test('says all quiet and lists nothing when everything is healthy', async () => {
  renderPage({
    delivery_configured: true,
    failed_jobs: 0,
    silent_instances: 0,
    review_queue: 0,
    alerts_by_status: {},
    alerts_by_delivery: {},
  })
  expect(await screen.findByText('All quiet')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Needs attention' })).not.toBeInTheDocument()
  expect(screen.getByText('No alerts yet')).toBeInTheDocument()
})

test('shows an error that says what to do when the stats cannot be loaded', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 500 })),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent(/Could not load the dashboard/)
})

test('shows how much media is kept only when keeping is on', async () => {
  renderPage()
  await screen.findByText('Messages today')
  expect(screen.queryByText('Media kept')).not.toBeInTheDocument()
})

test('shows the number and size of kept media when it is on', async () => {
  cleanup()
  renderPage({ media_policy: 'harmful', media_files: 7, media_bytes: 3 * 1024 * 1024 })
  const label = await screen.findByText('Media kept')
  expect(label.closest('div')).toHaveTextContent('3.0 MB')
  expect(label.closest('div')).toHaveTextContent('7')
})
