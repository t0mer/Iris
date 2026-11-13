import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { SetupReminders } from '../../src/components/SetupReminders'

test('skipped essentials remain and only the optional reminder can be dismissed', async () => {
  const essential = {
    id: 'openwa',
    title: 'Connect OpenWA',
    warning: 'Connect a live session.',
    dismissible: false,
  }
  const optional = {
    id: 'defaults',
    title: 'Review important defaults',
    warning: 'Review your defaults.',
    dismissible: true,
  }
  const fetch = vi.fn(async (_url: string, init?: RequestInit) =>
    Response.json({
      skipped: ['openwa'],
      steps: init?.method === 'POST' ? [essential] : [essential, optional],
    }),
  )
  vi.stubGlobal('fetch', fetch)
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SetupReminders userId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('Connect OpenWA · Skipped')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open setup checklist' })).toHaveAttribute(
    'href',
    '/setup',
  )
  expect(screen.queryByRole('button', { name: 'Dismiss Connect OpenWA' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss Review important defaults' }))
  await waitFor(() =>
    expect(screen.queryByText('Review important defaults')).not.toBeInTheDocument(),
  )
  expect(screen.getByText('Connect OpenWA · Skipped')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith(
    '/api/setup/reminders/dismiss',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ step: 'defaults' }) }),
  )
})
