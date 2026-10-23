import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LearningSharing } from '../../src/components/LearningSharing'

test('sharing stays off until the account explicitly approves and saves', async () => {
  const calls: RequestInit[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/me')
        return new Response(JSON.stringify({ id: 1, username: 'parent', role: 'parent' }))
      if (init?.method === 'PATCH') calls.push(init)
      return new Response(JSON.stringify({ enabled: false }))
    }),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <LearningSharing />
    </QueryClientProvider>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Learning sharing consent' }))
  await waitFor(() => expect(screen.getByRole('checkbox')).toBeEnabled())
  expect(screen.getByRole('checkbox')).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  expect(calls).toHaveLength(0)
  await userEvent.click(screen.getByRole('checkbox'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(calls).toHaveLength(1))
  expect(JSON.parse(String(calls[0].body))).toEqual({
    enabled: true,
    acknowledged_policy: 'synthetic-only-v1',
  })
})
