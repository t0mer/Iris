import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Setup } from '../../src/pages/Setup'
import { renderWithApp } from '../test-utils'

const state = {
  needs_setup: true,
  steps: ['openwa', 'notifiers', 'parents', 'children', 'ai', 'defaults'].map((id) => ({
    id,
    title: id,
    ready: false,
    warning: `${id} needs configuration`,
  })),
  warnings: ['No monitoring or delivery yet'],
  skipped: [],
  finished: false,
  active_channel: 'openwa',
  providers: { smtp: false, greenapi: false, openwa: false, telegram: false },
  ai_providers: [
    {
      id: 'ollama',
      title: 'Ollama classification',
      configured: true,
      required: true,
      tested: false,
    },
    {
      id: 'openai',
      title: 'OpenAI classification',
      configured: false,
      required: false,
      tested: false,
    },
    {
      id: 'local_whisper',
      title: 'Local Whisper transcription',
      configured: true,
      required: true,
      tested: false,
    },
  ],
}

test('AI providers test saved connections explicitly and unused providers remain optional', async () => {
  const calls = renderWithApp(<Setup />, { '/api/setup': state }, '/setup')
  await userEvent.click(await screen.findByRole('button', { name: '5. ai' }))
  expect(screen.getByText('OpenAI classification · Optional')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Test OpenAI classification' })).toBeDisabled()
  expect(calls.some((c) => c.url.startsWith('/api/setup/ai/test/'))).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Test Ollama classification' }))
  await waitFor(() => expect(calls.some((c) => c.url === '/api/setup/ai/test/ollama')).toBe(true))
  await userEvent.click(screen.getByRole('button', { name: '6. defaults' }))
  expect(screen.getByText(/Keep a database backup/)).toBeInTheDocument()
})

test('skipping setup keeps warnings and continuing acknowledges incomplete setup', async () => {
  const calls = renderWithApp(<Setup />, { '/api/setup': state }, '/setup')
  expect(await screen.findByRole('heading', { name: 'Set up Iris' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Skip this step' }))
  await waitFor(() =>
    expect(
      calls.some(
        (c) => c.url === '/api/setup/progress' && JSON.stringify(c.body) === '{"skip":"openwa"}',
      ),
    ).toBe(true),
  )
  expect(screen.getByRole('region', { name: 'Incomplete setup warnings' })).toHaveTextContent(
    'No monitoring or delivery yet',
  )
  await userEvent.click(
    screen.getByRole('button', { name: 'Continue to Home with these warnings' }),
  )
  await waitFor(() =>
    expect(
      calls.some(
        (c) =>
          c.url === '/api/setup/progress' &&
          JSON.stringify(c.body) === '{"finish":true,"acknowledge_incomplete":true}',
      ),
    ).toBe(true),
  )
})

test('connection checks are explicit and providers are tested separately', async () => {
  const calls = renderWithApp(<Setup />, { '/api/setup': state }, '/setup')
  await userEvent.click(await screen.findByRole('button', { name: 'Check connections' }))
  await waitFor(() =>
    expect(calls.some((c) => c.url === '/api/setup/check' && c.method === 'POST')).toBe(true),
  )
  await userEvent.click(screen.getByRole('button', { name: '2. notifiers' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test active alert channel (openwa)' }))
  await waitFor(() => expect(calls.some((c) => c.url === '/api/settings/test/alert')).toBe(true))
})
