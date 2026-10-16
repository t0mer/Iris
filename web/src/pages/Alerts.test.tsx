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
  expect(r.queryByText('I will find you')).not.toBeInTheDocument() // hidden by default
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תוכן' }))
  expect(r.getByText('I will find you')).toBeInTheDocument()
  expect(r.getByText(/בClass/)).toBeInTheDocument()
  expect(r.getByText('לא נשלחה')).toBeInTheDocument()
  expect(r.getByText(/אלימות/)).toBeInTheDocument()
})

test('a withheld alert shows no content, only that it is withheld', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, redacted: true, quote: null }]),
    '/api/instances': [],
  })
  expect(await screen.findByText(/התוכן הוסתר/)).toBeInTheDocument()
})

test('the status chips narrow the list through the address, so links from the dashboard work', async () => {
  const calls = renderWithApp(
    <Alerts />,
    { '/api/alerts': page([alert]), '/api/instances': [] },
    '/alerts?status=new',
  )
  await screen.findByRole('link', { name: /Noa/ })
  expect(screen.getByRole('button', { name: 'חדשה' })).toHaveAttribute('aria-pressed', 'true')
  expect(calls.some((c) => c.url.includes('status=new'))).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'נדחתה' }))
  expect(calls.some((c) => c.url.includes('status=dismissed'))).toBe(true)
})

test('an empty list says what to do, and differs when filters are the reason', async () => {
  renderWithApp(<Alerts />, { '/api/alerts': page([]), '/api/instances': [] })
  expect(await screen.findByText('אין עדיין התראות')).toBeInTheDocument()
})

test('with filters applied the empty state offers to clear them', async () => {
  renderWithApp(
    <Alerts />,
    { '/api/alerts': page([]), '/api/instances': [] },
    '/alerts?status=dismissed',
  )
  expect(await screen.findByText('אין התראות התואמות לסינון הזה')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: 'ניקוי סינונים' })[0])
  expect(await screen.findByText('אין עדיין התראות')).toBeInTheDocument()
})

test('warns that delivery is not set up when alerts were saved but could not be sent', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, delivery_error: 'alert delivery not configured' }]),
    '/api/instances': [],
  })
  expect(await screen.findByText(/משלוח ההתראות אינו מוגדר/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /הגדרת משלוח/ })).toHaveAttribute('href', '/settings')
})

const kept = { id: 7, kind: 'image', content_type: 'image/png', size_bytes: 2048, inline: true }

test('an alert with kept media says so in the list', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, media: kept }]),
    '/api/instances': [],
  })
  const row = await screen.findByRole('link', { name: /Noa/ })
  expect(within(row).getByText('תמונה נשמרה')).toBeInTheDocument()
  expect(within(row).queryByRole('link')).not.toBeInTheDocument() // no link nested in a link
})

test('a withheld alert never shows a media badge', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, redacted: true, quote: null, media: kept }]),
    '/api/instances': [],
  })
  await screen.findByText(/התוכן הוסתר/)
  expect(screen.queryByText('תמונה נשמרה')).not.toBeInTheDocument()
})

test('an alert whose text was kept out says to open it', async () => {
  renderWithApp(<Alerts />, {
    '/api/alerts': page([{ ...alert, quote: null }]),
    '/api/instances': [],
  })
  expect(await screen.findByText(/לא נכלל בהתראה/)).toBeInTheDocument()
})
