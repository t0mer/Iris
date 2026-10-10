import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LearningSettings } from '../../src/pages/LearningSettings'
import { renderWithApp } from '../test-utils'

test('admin can exclude a source and inspect baseline versus candidate evidence', async () => {
  const calls = renderWithApp(<LearningSettings />, {
    '/api/learning/examples': {
      items: [{ message_id: 7, verdict: 'harmful', enabled: true, source_valid: true }],
    },
    '/api/learning/runs': {
      summary: {
        sampled_runs: 1,
        reviewed_messages: 1,
        baseline: { false_positive: 0, false_negative: 1, review: 0 },
        candidate: { false_positive: 0, false_negative: 0, review: 0 },
      },
      items: [
        {
          id: 1,
          message_id: 8,
          baseline_verdict: 'safe',
          candidate_verdict: 'harmful',
          example_ids: [7],
        },
      ],
    },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Exclude example' }))
  await waitFor(() =>
    expect(
      calls.some(
        (c) =>
          c.url === '/api/learning/examples/7' &&
          c.method === 'PATCH' &&
          (c.body as { enabled: boolean }).enabled === false,
      ),
    ).toBe(true),
  )
  expect(screen.getByText(/safe → harmful/)).toBeInTheDocument()
  expect(screen.getByText(/not a held-out accuracy benchmark/)).toBeInTheDocument()
})

test('historical imports advance their cursor on the next batch', async () => {
  const calls = renderWithApp(<LearningSettings />, {
    '/api/learning/examples/import': { imported: 1, next_cursor: 99 },
    '/api/learning/examples': { items: [] },
    '/api/learning/runs': {
      summary: {
        sampled_runs: 0,
        reviewed_messages: 0,
        baseline: { false_positive: 0, false_negative: 0, review: 0 },
        candidate: { false_positive: 0, false_negative: 0, review: 0 },
      },
      items: [],
    },
  })
  const button = await screen.findByRole('button', { name: 'Import existing reviewed text' })
  await userEvent.click(button)
  await screen.findByText('Imported 1 reviewed text examples.')
  await userEvent.click(button)
  await waitFor(() =>
    expect(
      calls.some((c) => c.method === 'POST' && c.url === '/api/learning/examples/import?after=99'),
    ).toBe(true),
  )
})
