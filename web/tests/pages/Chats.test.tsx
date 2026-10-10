import userEvent from '@testing-library/user-event'
import { screen, waitFor } from '@testing-library/react'
import { renderWithApp } from '../test-utils'
import { Chats } from '../../src/pages/Chats'

const chat = (over: object) => ({
  id: 1,
  wa_chat_id: '972500000099-1500000000@g.us',
  name: null,
  is_group: true,
  kids: [{ id: 1, kid_name: 'Noa' }],
  message_count: 3,
  alert_count: 0,
  last_message_at: '2026-10-06T10:00:00Z',
  ...over,
})

test('shows a group by its name', async () => {
  renderWithApp(<Chats />, { '/api/chats': [chat({ name: 'Class 6B' })], '/api/auth/phones': [] })
  expect(await screen.findByText('Class 6B')).toBeInTheDocument()
})

test('never shows a raw group or chat id: unnamed ones get a plain label', async () => {
  renderWithApp(<Chats />, {
    '/api/auth/phones': [],
    '/api/chats': [chat({}), chat({ id: 2, wa_chat_id: '222222222222222@lid', is_group: false })],
  })
  expect(await screen.findByText('Unnamed group')).toBeInTheDocument()
  expect(screen.getByText('Direct chat', { selector: '.truncate' })).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent('@g.us')
  expect(document.body).not.toHaveTextContent('@lid')
})

test('restores message filters from the URL and carries them into the chat', async () => {
  const calls = renderWithApp(
    <Chats />,
    {
      '/api/chats': [chat({ name: 'Filtered class' })],
      '/api/auth/phones': [{ id: 1, kid_name: 'Noa' }],
    },
    '/chats?q=שלום&instance_id=1&type=text&verdict=harmful&sender=Dan&when=7d',
  )
  const link = await screen.findByRole('link', { name: /Filtered class/ })
  const request = new URL(calls.find((c) => c.url.startsWith('/api/chats'))!.url, 'http://iris')
  expect(request.searchParams.get('q')).toBe('שלום')
  expect(request.searchParams.get('instance_id')).toBe('1')
  expect(request.searchParams.get('type')).toBe('text')
  expect(request.searchParams.get('verdict')).toBe('harmful')
  expect(request.searchParams.get('sender')).toBe('Dan')
  expect(request.searchParams.has('from')).toBe(true)
  const target = new URL(link.getAttribute('href')!, 'http://iris')
  expect(target.searchParams.get('chat')).toBe('1')
  expect(target.searchParams.get('q')).toBe('שלום')
  expect(target.searchParams.get('when')).toBe('7d')
})

test('clears filters from the empty result', async () => {
  const user = userEvent.setup()
  const calls = renderWithApp(
    <Chats />,
    { '/api/chats': [], '/api/auth/phones': [] },
    '/chats?q=missing&type=audio',
  )
  expect(await screen.findByText('No chats match')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Clear search and filters' }))
  await waitFor(() => expect(calls.some((c) => c.url === '/api/chats?')).toBe(true))
  expect(screen.getByRole('searchbox')).toHaveValue('')
})
