import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { MemoryRouter } from 'react-router-dom'
import { Messages } from './Messages'

test('renders messages with a highlighted snippet and kid names', async () => {
  const page = {
    items: [
      {
        id: 1,
        chat_id: 1,
        chat_name: 'Class',
        is_group: true,
        sender_name: 'Dan',
        from_me: false,
        type: 'text',
        text: 'שלום עולם',
        transcript: null,
        snippet: '\x02שלום\x03 עולם',
        sent_at: '2026-10-06T10:00:00Z',
        status: 'pending',
        verdict: null,
        redacted: false,
        kids: [{ id: 1, kid_name: 'Noa' }],
      },
    ],
    total: 1,
    page: 1,
    page_size: 25,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(JSON.stringify(url.startsWith('/api/instances') ? [] : page), { status: 200 }),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Messages />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect((await screen.findByText('שלום')).tagName).toBe('MARK')
  expect(screen.getByText(/Noa/)).toBeInTheDocument()
})

// --- regression tests for the review findings -------------------------------------------------

const emptyPage = { items: [], total: 0, page: 1, page_size: 25 }
const messageCalls = (calls: { url: string }[]) =>
  calls.filter((c) => c.url.startsWith('/api/messages'))

test('a relative date filter fetches once instead of refetching on every render', async () => {
  const calls = renderWithApp(
    <Messages />,
    { '/api/messages': emptyPage, '/api/instances': [] },
    '/messages?when=7d',
  )
  await screen.findByText('No messages match')
  await new Promise((r) => setTimeout(r, 600)) // long enough for a render loop to pile up requests
  expect(messageCalls(calls).length).toBeLessThanOrEqual(2)
  expect(messageCalls(calls)[0].url).toContain('from=')
})

test('the debounced search does not revert a filter changed while the timer was pending', async () => {
  const calls = renderWithApp(
    <Messages />,
    { '/api/messages': emptyPage, '/api/instances': [] },
    '/messages',
  )
  await screen.findByText('No messages yet')
  await userEvent.type(screen.getByRole('searchbox', { name: 'Search messages' }), 'hello')
  await userEvent.click(screen.getByRole('button', { name: '7 days' })) // before the 300 ms pause ends
  await new Promise((r) => setTimeout(r, 700))
  const last = messageCalls(calls).at(-1)!.url
  expect(last).toContain('q=hello')
  expect(last).toContain('from=') // the chip survived
})

test('a hand-edited page number never reaches the server as NaN', async () => {
  const calls = renderWithApp(
    <Messages />,
    { '/api/messages': emptyPage, '/api/instances': [] },
    '/messages?page=abc',
  )
  await screen.findByText('No messages yet')
  expect(messageCalls(calls)[0].url).toContain('page=1')
  expect(messageCalls(calls)[0].url).not.toContain('NaN')
})
