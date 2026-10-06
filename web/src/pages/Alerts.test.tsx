import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Alerts } from './Alerts'

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
  renderWithApp(<Alerts />, { '/api/alerts': page([alert]), '/api/instances': [] })
  const row = await screen.findByRole('link', { name: /Noa/ })
  const r = within(row)
  expect(r.getByText('I will find you')).toBeInTheDocument()
  expect(r.getByText(/in Class/)).toBeInTheDocument()
  expect(r.getByText('Not delivered')).toBeInTheDocument()
  expect(r.getByText(/violence/)).toBeInTheDocument()
})

test('a withheld alert shows no content, only that it is withheld', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, redacted: true, quote: null }]),
    '/api/instances': [],
  })
  expect(await screen.findByText(/Content withheld/)).toBeInTheDocument()
})

test('the status chips narrow the list through the address, so links from the dashboard work', async () => {
  const calls = renderWithApp(
    <Alerts />,
    { '/api/alerts': page([alert]), '/api/instances': [] },
    '/alerts?status=new',
  )
  await screen.findByRole('link', { name: /Noa/ })
  expect(screen.getByRole('button', { name: 'New' })).toHaveAttribute('aria-pressed', 'true')
  expect(calls.some((c) => c.url.includes('status=new'))).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Dismissed' }))
  expect(calls.some((c) => c.url.includes('status=dismissed'))).toBe(true)
})

test('an empty list says what to do, and differs when filters are the reason', async () => {
  renderWithApp(<Alerts />, { '/api/alerts': page([]), '/api/instances': [] })
  expect(await screen.findByText('No alerts yet')).toBeInTheDocument()
})

test('with filters applied the empty state offers to clear them', async () => {
  renderWithApp(
    <Alerts />,
    { '/api/alerts': page([]), '/api/instances': [] },
    '/alerts?status=dismissed',
  )
  expect(await screen.findByText('No alerts match these filters')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  expect(await screen.findByText('No alerts yet')).toBeInTheDocument()
})

test('warns that delivery is not set up when alerts were saved but could not be sent', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, delivery_error: 'alert delivery not configured' }]),
    '/api/instances': [],
  })
  expect(await screen.findByText(/Alert delivery is not set up/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Set up delivery/ })).toHaveAttribute('href', '/settings')
})
