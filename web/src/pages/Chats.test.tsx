import { screen } from '@testing-library/react'
import { renderWithApp } from '../test-utils'
import { Chats } from './Chats'

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
  renderWithApp(<Chats />, { '/api/chats': [chat({ name: 'Class 6B' })] })
  expect(await screen.findByText('Class 6B')).toBeInTheDocument()
})

test('never shows a raw group or chat id: unnamed ones get a plain label', async () => {
  renderWithApp(<Chats />, {
    '/api/chats': [chat({}), chat({ id: 2, wa_chat_id: '222222222222222@lid', is_group: false })],
  })
  expect(await screen.findByText('Unnamed group')).toBeInTheDocument()
  expect(screen.getByText('Direct chat', { selector: '.truncate' })).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent('@g.us')
  expect(document.body).not.toHaveTextContent('@lid')
})
