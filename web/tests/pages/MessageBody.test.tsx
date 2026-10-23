import { render, screen } from '@testing-library/react'
import { MessageBody } from '../../src/components/MessageBody'
import type { Message } from '../../src/lib/types'

const empty = {
  type: 'other',
  text: null,
  transcript: null,
  redacted: false,
  revoked_at: null,
} as Message

test('explains deletion markers instead of showing other', () => {
  render(<MessageBody m={{ ...empty, raw_type: 'revoked' }} />)
  expect(screen.getByText(/Deleted WhatsApp message/)).toBeInTheDocument()
  expect(screen.queryByText('[other]')).not.toBeInTheDocument()
})
test('explains unsupported content without guessing its contents', () => {
  render(<MessageBody m={{ ...empty, raw_type: 'unknown' }} />)
  expect(screen.getByText(/OpenWA provided no readable content/)).toBeInTheDocument()
})
test('names an empty poll and keeps real Hebrew content concealed', () => {
  const { rerender } = render(<MessageBody m={{ ...empty, type: 'poll' }} />)
  expect(screen.getByText(/WhatsApp poll/)).toBeInTheDocument()
  rerender(<MessageBody m={{ ...empty, type: 'poll', text: 'מה עושים היום?' }} />)
  expect(screen.queryByText('מה עושים היום?')).not.toBeInTheDocument()
  rerender(<MessageBody m={{ ...empty, type: 'poll', text: 'מה עושים היום?' }} revealed />)
  expect(screen.getByText('מה עושים היום?')).toBeInTheDocument()
})
test('withheld content stays withheld even when type is known', () => {
  render(
    <MessageBody
      m={{ ...empty, type: 'poll', raw_type: 'poll', text: 'secret', redacted: true }}
      revealed
    />,
  )
  expect(screen.getByText(/Content withheld/)).toBeInTheDocument()
  expect(screen.queryByText('secret')).not.toBeInTheDocument()
})
