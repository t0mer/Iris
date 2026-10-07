import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { renderWithApp } from '../test-utils'
import { AlertDetail } from './AlertDetail'

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

function page(a: unknown) {
  return renderWithApp(
    <Routes>
      <Route path="/alerts/:id" element={<AlertDetail />} />
    </Routes>,
    { '/api/alerts/3': a },
    '/alerts/3',
  )
}

test('shows the kept media under the quote, with a link to its own page', async () => {
  page({ ...alert, media })
  expect(await screen.findByRole('heading', { name: 'Kept media' })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /photo kept/ })).toHaveAttribute('src', '/api/media/7')
  expect(screen.getByRole('link', { name: 'Open on its own page' })).toHaveAttribute(
    'href',
    '/media/7',
  )
})

test('has no media section when nothing is kept', async () => {
  page({ ...alert, media: null })
  await screen.findByText('I will find you')
  expect(screen.queryByRole('heading', { name: 'Kept media' })).not.toBeInTheDocument()
})

test('never shows media for a withheld alert', async () => {
  page({ ...alert, redacted: true, quote: null, media })
  await screen.findByText(/The content is withheld/)
  expect(screen.queryByRole('img', { name: /photo kept/ })).not.toBeInTheDocument()
})
