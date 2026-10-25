import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LearningSettings } from '../../src/pages/LearningSettings'
import { renderWithApp } from '../test-utils'

test('paired conversation evidence shows aggregate wins, losses and significance', async () => {
  renderWithApp(<LearningSettings />, {
    '/api/learning/evaluation': {
      running: false,
      stale: false,
      result: {
        source: 'held_out_human_reviews',
        evaluated: 100,
        expected: 100,
        failures: 0,
        paired: { unit: 'conversation', improved: 5, regressed: 0, one_sided_p: 0.03125 },
      },
    },
    '/api/learning/examples': { items: [] },
    '/api/learning/runs': {
      summary: { sampled_runs: 0, reviewed_messages: 0, baseline: {}, candidate: {} },
      items: [],
    },
  })
  expect(
    await screen.findByText('5 conversations improved; 0 regressed. Paired test p: 0.0313.'),
  ).toBeVisible()
})

test('an old reference-pack result remains visible with a stale-result notice', async () => {
  renderWithApp(<LearningSettings />, {
    '/api/learning/evaluation': {
      running: false,
      stale: true,
      result: { source: 'synthetic', evaluated: 12, expected: 12, failures: 0 },
    },
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
  expect(
    await screen.findByText(
      'The model settings, model version or evaluation policy have changed. Run a new evaluation.',
    ),
  ).toBeVisible()
  expect(screen.getByText(/12 \/ 12/)).toBeVisible()
})

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

test('saved progress stays visible while an administrator inspects historical reports', async () => {
  renderWithApp(<LearningSettings />, {
    '/api/learning/evaluation': {
      running: true,
      result: {
        evaluation_id: 'current',
        source: 'held_out_human_reviews',
        evaluated: 1,
        expected: 3,
        pending: 2,
      },
      history: [
        {
          stale: true,
          result: {
            evaluation_id: 'old',
            source: 'synthetic',
            checked_at: '2026-10-01T12:00:00Z',
            evaluated: 28,
            expected: 28,
          },
        },
      ],
    },
    '/api/learning/examples': { items: [] },
    '/api/learning/runs': {
      summary: { sampled_runs: 0, reviewed_messages: 0, baseline: {}, candidate: {} },
      items: [],
    },
  })
  expect(
    await screen.findByText('2 checks remaining. Progress is saved automatically.'),
  ).toBeVisible()
  expect(screen.getByRole('button', { name: 'Evaluate held-out local reviews' })).toBeDisabled()
  await userEvent.click(screen.getByText('Previous evaluation reports'))
  await userEvent.click(screen.getByRole('button', { name: /Synthetic benchmark/ }))
  expect(
    screen.getByText(
      'The model settings, model version or evaluation policy have changed. Run a new evaluation.',
    ),
  ).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Show current evaluation' }))
  expect(screen.getByText('2 checks remaining. Progress is saved automatically.')).toBeVisible()
})

test('model version remains visible when the provider identity cannot be verified', async () => {
  renderWithApp(<LearningSettings />, {
    '/api/learning/evaluation': {
      running: false,
      stale: true,
      model_identity_status: 'unavailable',
      failed: true,
      result: {
        source: 'synthetic',
        evaluated: 28,
        model_identity: { classifier: 'a'.repeat(64), embedding: 'b'.repeat(64) },
      },
    },
    '/api/learning/examples': { items: [] },
    '/api/learning/runs': {
      summary: { sampled_runs: 0, reviewed_messages: 0, baseline: {}, candidate: {} },
      items: [],
    },
  })
  expect(
    await screen.findByText(
      'Model identity could not be verified. Previous results are not current.',
    ),
  ).toBeVisible()
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Learning evaluation failed. Check Jobs and retry.',
  )
  expect(screen.getByRole('link', { name: 'Jobs' })).toHaveAttribute('href', '/jobs')
  expect(screen.getByTitle('a'.repeat(64))).toHaveTextContent('a'.repeat(12))
  expect(screen.getByTitle('b'.repeat(64))).toHaveTextContent('b'.repeat(12))
})
