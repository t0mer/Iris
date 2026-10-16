import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  const list = within(await screen.findByRole('region', { name: 'דורש תשומת לב' }))
  expect(list.getByText(/משלוח ההתראות אינו מוגדר/)).toBeInTheDocument()
  expect(list.getByText('4 משימות נכשלו')).toBeInTheDocument()
  expect(list.getByText(/מעולם לא התקבלו מהם הודעות/)).toBeInTheDocument()
  expect(list.getByText(/3 התראות חדשות לקריאה/)).toBeInTheDocument()
  expect(list.getByText(/2 הודעות שאיריס לא הצליחה לסווג/)).toBeInTheDocument()
  expect(screen.getByText('3 התראות ו־2 לבדיקה דורשות תשומת לב')).toBeInTheDocument()
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
  expect(await screen.findByText('הכול שקט')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'דורש תשומת לב' })).not.toBeInTheDocument()
  expect(screen.getByText('אין עדיין התראות')).toBeInTheDocument()
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
  expect(await screen.findByRole('alert')).toHaveTextContent(/לא ניתן היה לטעון את לוח הבקרה/)
})

test('shows how much media is kept only when keeping is on', async () => {
  renderPage()
  await screen.findByText('הודעות היום')
  expect(screen.queryByText('מדיה שנשמרה')).not.toBeInTheDocument()
})

test('shows the number and size of kept media when it is on', async () => {
  cleanup()
  renderPage({ media_policy: 'harmful', media_files: 7, media_bytes: 3 * 1024 * 1024 })
  const label = await screen.findByText('מדיה שנשמרה')
  expect(label.closest('div')).toHaveTextContent('3.0 מ״ב')
  expect(label.closest('div')).toHaveTextContent('7')
})

test('still shows kept media after keeping was turned off', async () => {
  cleanup()
  renderPage({ media_policy: 'off', media_files: 2, media_bytes: 2048 })
  expect(await screen.findByText('מדיה שנשמרה')).toBeInTheDocument()
})

test('recent alerts show no quote until the eye is pressed', async () => {
  cleanup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.startsWith('/api/stats')) return new Response(JSON.stringify(stats))
      const alert = {
        id: 1,
        message_id: 1,
        chat_id: 1,
        categories: ['violence'],
        max_score: 0.9,
        kid_names: ['Noa'],
        chat_name: 'Class',
        sender_name: 'Dan',
        quote: 'a private quote',
        redacted: false,
        status: 'new',
        delivery_status: 'sent',
        delivery_error: null,
        notified_at: null,
        created_at: '2026-10-06T10:00:00Z',
        edited_at: null,
        revoked_at: null,
      }
      return new Response(JSON.stringify({ items: [alert], total: 1, page: 1, page_size: 5 }))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await screen.findByText('התראות אחרונות')
  expect(screen.queryByText('a private quote')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תוכן' }))
  expect(await screen.findByText('a private quote')).toBeInTheDocument()
})

test('warns when no children, parents or alert sender are configured', async () => {
  renderPage({
    children: 0,
    parent_recipients: 0,
    alert_phones: 0,
    alert_sender_configured: false,
    alerts_by_status: {},
    review_queue: 0,
  })
  expect(await screen.findByText(/לא הוגדר טלפון של ילד/)).toBeInTheDocument()
  expect(screen.getByText(/לא הוגדרו נמענים/)).toBeInTheDocument()
  expect(screen.getByText(/לא הוגדר טלפון לשליחת/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'ילדים: 0' })).toHaveAttribute('href', '/instances')
  expect(screen.getByRole('link', { name: 'הורים: 0' })).toHaveAttribute(
    'href',
    '/settings?tab=Alerts',
  )
  expect(screen.getByRole('link', { name: 'טלפונים להתראות: 0' })).toBeInTheDocument()
})
