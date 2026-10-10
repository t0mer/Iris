import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SetupCheck } from '../../src/components/SetupCheck'
import { renderWithApp } from '../test-utils'

test('shows success beside its button and disables repeat clicks', async () => {
  renderWithApp(<SetupCheck path="/api/setup/ai/test/ollama" label="Test Ollama" />, {
    '/api/setup/ai/test/ollama': { ok: true, detail: 'Ollama answered successfully' },
  })
  const button = screen.getByRole('button', { name: 'Test Ollama' })
  await userEvent.click(button)
  expect(await screen.findByRole('status')).toHaveTextContent('Ollama answered successfully')
  expect(button).toBeDisabled()
})

test('shows failure beside its button and allows retry', async () => {
  renderWithApp(<SetupCheck path="/api/setup/ai/test/local_whisper" label="Test Whisper" />, {
    '/api/setup/ai/test/local_whisper': { ok: false, detail: 'Authentication failed' },
  })
  const button = screen.getByRole('button', { name: 'Test Whisper' })
  await userEvent.click(button)
  expect(await screen.findByRole('alert')).toHaveTextContent('Authentication failed')
  await waitFor(() => expect(button).toBeEnabled())
})

test('saved success is visible and queued delivery does not count as success', async () => {
  renderWithApp(<SetupCheck path="/api/settings/test/alert" label="Test alerts" />, {
    '/api/settings/test/alert': { ok: true, detail: 'Test notification queued' },
  })
  const button = screen.getByRole('button', { name: 'Test alerts' })
  await userEvent.click(button)
  expect(await screen.findByRole('status')).toHaveTextContent('queued')
  expect(button).toBeEnabled()
})

test('renders a persisted success with a disabled button', () => {
  renderWithApp(
    <SetupCheck
      path="/api/setup/ai/test/ollama"
      label="Test Ollama"
      passed
      detail="Valid moderation returned"
    />,
    {},
  )
  expect(screen.getByRole('status')).toHaveTextContent('Valid moderation returned')
  expect(screen.getByRole('button', { name: 'Test Ollama' })).toBeDisabled()
})
