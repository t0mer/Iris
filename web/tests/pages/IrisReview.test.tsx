import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { IrisReview } from '../../src/pages/IrisReview'
import { renderWithApp } from '../test-utils'

const message = {
  id: 7,
  chat_id: 1,
  chat_name: 'School',
  kids: [{ id: 1, kid_name: 'Child' }],
  type: 'text',
  status: 'processing',
  text: 'Test',
  sent_at: '2026-10-10T10:00:00Z',
  redacted: false,
}

test('AI queue shows a thinking icon and skip action but no human decision buttons', async () => {
  const calls = renderWithApp(<IrisReview />, {
    '/api/review?view=ai': { items: [{ message }], total: 1 },
    '/api/review/7/skip-ai': { ok: true, human_review_view: 'pending' },
  })
  expect(await screen.findByLabelText('AI thinking')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Mark safe' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Mark harmful' })).not.toBeInTheDocument()
  expect(screen.queryByText('Note: additional options')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Skip AI → Human review' }))
  await waitFor(() =>
    expect(calls.some((c) => c.url === '/api/review/7/skip-ai' && c.method === 'POST')).toBe(true),
  )
  expect(await screen.findByText('Moved to human Review.')).toBeInTheDocument()
})

test('watch users can see thinking but cannot skip AI', async () => {
  renderWithApp(<IrisReview />, {
    '/api/auth/me': { id: 2, role: 'watch' },
    '/api/review?view=ai': { items: [{ message }], total: 1 },
  })
  await screen.findByLabelText('AI thinking')
  expect(screen.queryByRole('button', { name: 'Skip AI → Human review' })).not.toBeInTheDocument()
})
