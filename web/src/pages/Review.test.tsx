import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Review } from './Review'

const item = {
  message: {
    id: 9,
    chat_id: 1,
    chat_name: 'Maya',
    is_group: false,
    sender_name: 'Maya',
    from_me: false,
    type: 'text',
    text: "lol you're dead meat",
    transcript: null,
    snippet: null,
    sent_at: '2026-10-06T10:00:00Z',
    status: 'done',
    verdict: 'review',
    redacted: false,
    kids: [{ id: 1, kid_name: 'Noa' }],
    failure: null,
  },
  classifications: [
    {
      id: 1,
      stage: 'context',
      input_kind: 'text',
      model: 'm',
      scores: { harassment: 0.41 },
      flagged_categories: ['harassment'],
      band: 'inconclusive',
      context_message_ids: [],
      latency_ms: 1,
    },
  ],
}

test('shows the message with who and where, and explains why it is unclear on request', async () => {
  renderWithApp(<Review />, { '/api/review': { items: [item], total: 1, page: 1, page_size: 25 } })
  expect(await screen.findByText("lol you're dead meat")).toBeInTheDocument()
  expect(screen.getByText(/in Maya/)).toBeInTheDocument()
  await userEvent.click(screen.getByText('Why it is unclear'))
  expect(screen.getByText('harassment')).toBeInTheDocument()
})

test('marking harmful and marking safe each send the decision', async () => {
  const calls = renderWithApp(<Review />, {
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  await userEvent.click(await screen.findByRole('button', { name: /Mark harmful/ }))
  expect(calls.find((c) => c.method === 'POST')).toMatchObject({
    url: '/api/review/9',
    body: { resolution: 'harmful' },
  })
  expect(await screen.findByText('Marked harmful. An alert was created.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Mark safe/ }))
  expect(calls.filter((c) => c.method === 'POST')[1]).toMatchObject({
    body: { resolution: 'safe' },
  })
})

test('an empty queue is an invitation, not a blank page', async () => {
  renderWithApp(<Review />, { '/api/review': { items: [], total: 0, page: 1, page_size: 25 } })
  expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
})
