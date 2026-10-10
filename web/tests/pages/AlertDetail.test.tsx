import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { renderWithApp } from '../test-utils'
import { AlertDetail } from '../../src/pages/AlertDetail'
import * as apiModule from '../../src/lib/api'

const alert = {
  id: 3,
  message_id: 4,
  chat_id: 1,
  categories: ['violence'],
  max_score: 0.94,
  kid_names: ['Noa'],
  chat_name: 'Class',
  sender_name: 'Dan',
  quote: 'I will find you',
  redacted: false,
  status: 'new',
  delivery_status: 'sent',
  delivery_error: null,
  notified_at: '2026-10-06T10:00:00Z',
  created_at: '2026-10-06T10:00:00Z',
  edited_at: null,
  revoked_at: null,
  message_type: 'image',
  sent_at: '2026-10-06T09:59:00Z',
  classifications: [],
}
const media = { id: 7, kind: 'image', content_type: 'image/png', size_bytes: 2048, inline: true }

test('a server error offers retry instead of claiming the alert was deleted', async () => {
  const request = vi
    .spyOn(apiModule, 'api')
    .mockRejectedValue(new apiModule.ApiError(500, 'Server error'))
  page({})
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load this alert')
  expect(screen.queryByText(/This alert no longer exists/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  request.mockRestore()
})

function page(a: unknown) {
  return renderWithApp(
    <Routes>
      <Route path="/alerts/:id" element={<AlertDetail />} />
    </Routes>,
    { '/api/auth/me': { username: 'admin', role: 'admin', id: 1 }, '/api/alerts/3': a },
    '/alerts/3',
  )
}

test('opening an alert marks it read once and can restore it to the personal unseen list', async () => {
  const calls = page(alert)
  await screen.findByRole('heading', { name: 'The message' })
  await waitFor(() =>
    expect(calls.filter((c) => c.method === 'POST' && c.url === '/api/alerts/3/seen')).toHaveLength(
      1,
    ),
  )
  expect(calls.find((c) => c.method === 'POST' && c.url === '/api/alerts/3/seen')?.body).toEqual({
    seen: true,
  })
  expect(screen.queryByRole('button', { name: 'Mark as seen' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Mark unseen' }))
  await waitFor(() =>
    expect(calls.filter((c) => c.url === '/api/alerts/3/seen' && c.method === 'POST')).toHaveLength(
      2,
    ),
  )
  expect(
    calls.filter((c) => c.url === '/api/alerts/3/seen' && c.method === 'POST')[1].body,
  ).toEqual({ seen: false })
})

test('everything stored is hidden until the eye is pressed', async () => {
  const calls = page({ ...alert, media })
  await screen.findByRole('heading', { name: 'Kept media' })
  expect(screen.queryByText('I will find you')).not.toBeInTheDocument()
  expect(screen.queryByRole('img', { name: /photo kept/ })).not.toBeInTheDocument()
  expect(screen.getByText('Photo hidden')).toBeInTheDocument()
  expect(calls.every((c) => !c.url.includes('/api/media/7'))).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(await screen.findByText('I will find you')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /photo kept/ })).toHaveAttribute('src', '/api/media/7')
  await userEvent.click(screen.getByRole('button', { name: 'Hide content' }))
  expect(screen.queryByText('I will find you')).not.toBeInTheDocument()
})

test('keeps a link to the media on its own page', async () => {
  page({ ...alert, media })
  expect(await screen.findByRole('link', { name: 'Open on its own page' })).toHaveAttribute(
    'href',
    '/media/7',
  )
})

test('has no media section when nothing is kept', async () => {
  page({ ...alert, media: null })
  await screen.findByRole('heading', { name: 'The message' })
  expect(screen.queryByRole('heading', { name: 'Kept media' })).not.toBeInTheDocument()
})

test('a withheld alert says why there is nothing to show, and has no eye', async () => {
  page({ ...alert, redacted: true, quote: null, media })
  expect(
    await screen.findByText(/Withheld on purpose, so there is nothing to show/),
  ).toBeInTheDocument()
  expect(screen.getByText(/never stored the content/)).toBeInTheDocument()
  expect(screen.getByText(/open the chat directly in WhatsApp/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Show content/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('img', { name: /photo kept/ })).not.toBeInTheDocument()
})

test('an uncertain item kept out of the alert points to the conversation', async () => {
  page({ ...alert, quote: null, media: null })
  expect(await screen.findByText('Kept out of this alert')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Read it in the conversation/ })).toHaveAttribute(
    'href',
    '/messages/4',
  )
  expect(screen.queryByRole('button', { name: /Show content/ })).not.toBeInTheDocument()
})

test('partial delivery has a clear recipient label', async () => {
  page({ ...alert, delivery_status: 'partial' })
  expect(await screen.findByText('Delivered to some recipients')).toBeInTheDocument()
})
