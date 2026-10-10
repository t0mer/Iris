import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Alerts } from '../../src/pages/Alerts'

const alert = {
  id: 1,
  message_id: 1,
  chat_id: 1,
  categories: ['violence', 'harassment'],
  max_score: 0.94,
  kid_names: ['Noa'],
  chat_name: 'Class',
  sender_name: 'Dan',
  quote: 'I will find you',
  redacted: false,
  status: 'new',
  delivery_status: 'failed',
  delivery_error: 'OpenWA: Session is not active',
  notified_at: null,
  created_at: '2026-10-06T10:00:00Z',
}
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 25 })

test('lists alerts with who, where, what was said and what state they are in', async () => {
  renderWithApp(<Alerts />, { '/api/alerts': page([alert]), '/api/auth/phones': [] })
  const row = await screen.findByRole('link', { name: /Noa/ })
  const r = within(row)
  expect(r.queryByText('I will find you')).not.toBeInTheDocument() // hidden by default
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(r.getByText('I will find you')).toBeInTheDocument()
  expect(r.getByText(/in Class/)).toBeInTheDocument()
  expect(r.getByText('Not delivered')).toBeInTheDocument()
  expect(r.getByText(/violence/)).toBeInTheDocument()
})

test('a withheld alert shows no content, only that it is withheld', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, redacted: true, quote: null }]),
    '/api/auth/phones': [],
  })
  expect(await screen.findByText(/Content withheld/)).toBeInTheDocument()
})

test('the status chips narrow the list through the address, so links from the dashboard work', async () => {
  const calls = renderWithApp(
    <Alerts />,
    { '/api/alerts': page([alert]), '/api/auth/phones': [] },
    '/alerts?status=new',
  )
  await screen.findByRole('link', { name: /Noa/ })
  expect(screen.getByRole('button', { name: 'Unseen' })).toHaveAttribute('aria-pressed', 'true')
  expect(calls.some((c) => c.url.includes('view=unseen'))).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Dismissed' }))
  expect(calls.some((c) => c.url.includes('view=dismissed'))).toBe(true)
})

test('an empty list says what to do, and differs when filters are the reason', async () => {
  const calls = renderWithApp(<Alerts />, { '/api/alerts': page([]), '/api/auth/phones': [] })
  expect(await screen.findByText('No unseen alerts')).toBeInTheDocument()
  expect(calls.some((c) => c.url.includes('view=unseen'))).toBe(true)
  expect(calls.some((c) => c.method === 'POST')).toBe(false)
})

test('with filters applied the empty state offers to clear them', async () => {
  renderWithApp(
    <Alerts />,
    { '/api/alerts': page([]), '/api/auth/phones': [] },
    '/alerts?status=dismissed',
  )
  expect(await screen.findByText('No alerts match these filters')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  expect(await screen.findByText('No unseen alerts')).toBeInTheDocument()
})

test('warns that delivery is not set up when alerts were saved but could not be sent', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([]),
    '/api/stats': { delivery_configured: false },
    '/api/auth/phones': [],
  })
  expect(await screen.findByText(/Alert delivery is not set up/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Set up delivery/ })).toHaveAttribute(
    'href',
    '/settings?tab=Notifications',
  )
})

const kept = { id: 7, kind: 'image', content_type: 'image/png', size_bytes: 2048, inline: true }

test('an alert with kept media says so in the list', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, media: kept }]),
    '/api/auth/phones': [],
  })
  const row = await screen.findByRole('link', { name: /Noa/ })
  expect(within(row).getByText('Photo kept')).toBeInTheDocument()
  expect(within(row).queryByRole('link')).not.toBeInTheDocument() // no link nested in a link
})

test('a withheld alert never shows a media badge', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, redacted: true, quote: null, media: kept }]),
    '/api/auth/phones': [],
  })
  await screen.findByText(/Content withheld/)
  expect(screen.queryByText('Photo kept')).not.toBeInTheDocument()
})

test('an alert whose text was kept out says to open it', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, quote: null }]),
    '/api/auth/phones': [],
  })
  expect(await screen.findByText(/Kept out of the alert/)).toBeInTheDocument()
})

test('entering Alerts marks the displayed batch read once and keeps it readable', async () => {
  const calls = renderWithApp(<Alerts />, {
    '/api/alerts/seen': { marked: 1, seen_at: '2026-10-10T10:00:00Z' },
    '/api/alerts': page([alert]),
    '/api/auth/phones': [],
  })
  await screen.findByRole('link', { name: /Noa/ })
  await waitFor(() => expect(calls.filter((c) => c.url === '/api/alerts/seen')).toHaveLength(1))
  expect(calls.find((c) => c.url === '/api/alerts/seen')?.body).toEqual({ alert_ids: [1] })
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(screen.getByText('I will find you')).toBeInTheDocument()
  expect(calls.filter((c) => c.url === '/api/alerts/seen')).toHaveLength(1)
})

test('read events do not automatically drain additional unseen pages', async () => {
  const calls = renderWithApp(<Alerts />, {
    '/api/alerts/seen': { marked: 1, seen_at: '2026-10-10T10:00:00Z' },
    '/api/alerts': { ...page([alert]), total: 26 },
    '/api/auth/phones': [],
  })
  await screen.findByText(/1 alert marked read for you/)
  expect(calls.filter((c) => c.url.startsWith('/api/alerts?'))).toHaveLength(1)
  await userEvent.click(screen.getByRole('button', { name: 'Next unread alerts' }))
  await waitFor(() => expect(calls.filter((c) => c.url.startsWith('/api/alerts?'))).toHaveLength(2))
  expect(
    calls.filter((c) => c.url.startsWith('/api/alerts?')).every((c) => c.url.includes('page=1')),
  ).toBe(true)
})

test('the missing-media link selects All and filters previously read alerts', async () => {
  const calls = renderWithApp(
    <Alerts />,
    {
      '/api/alerts': page([{ ...alert, status: 'acknowledged' }]),
      '/api/auth/phones': [],
    },
    '/alerts?view=all&media=missing',
  )
  await screen.findByRole('link', { name: /Noa/ })
  expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('combobox', { name: 'Media' })).toHaveValue('missing')
  expect(calls.some((c) => c.url.includes('view=all') && c.url.includes('media=missing'))).toBe(
    true,
  )
  expect(calls.some((c) => c.method === 'POST')).toBe(false)
})
