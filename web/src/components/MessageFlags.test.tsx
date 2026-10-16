import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { revokedClass } from '../lib/revoked'
import { renderWithApp } from '../test-utils'
import { MessageFlags } from './MessageFlags'

const base = { id: 7, edited_at: null, revoked_at: null }

test('an untouched message shows no markers and no border', () => {
  renderWithApp(<MessageFlags m={base} history />, {})
  expect(screen.queryByText('נערכה')).not.toBeInTheDocument()
  expect(revokedClass(base)).toBe('')
})

test('a deleted message is labelled in words and gets the red border', () => {
  const m = { ...base, revoked_at: '2026-10-07T10:00:00Z' }
  renderWithApp(<MessageFlags m={m} />, {})
  expect(screen.getByText('נמחקה אצל כולם')).toBeInTheDocument()
  expect(revokedClass(m)).toContain('border-danger')
  expect(revokedClass(m, 'row')).toContain('ring-danger')
})

test('inside a link the edited marker is plain text, not a button', () => {
  renderWithApp(<MessageFlags m={{ ...base, edited_at: '2026-10-07T10:00:00Z' }} />, {})
  expect(screen.getByText('נערכה')).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

const detail = {
  id: 7,
  text: 'third wording',
  redacted: false,
  sent_at: '2026-10-07T09:00:00Z',
  edited_at: '2026-10-07T10:00:00Z',
  revoked_at: null,
  revisions: [
    { text: 'first wording', replaced_at: '2026-10-07T09:30:00Z' },
    { text: 'second wording', replaced_at: '2026-10-07T10:00:00Z' },
  ],
}

test('the edited button opens the history, newest first, ending with the original', async () => {
  renderWithApp(<MessageFlags m={{ ...base, edited_at: detail.edited_at }} history />, {
    '/api/messages/7': detail,
  })
  await userEvent.click(screen.getByRole('button', { name: /הצגת היסטוריית העריכה/ }))
  const dialog = await screen.findByRole('dialog', { name: 'היסטוריית עריכה' })
  await screen.findAllByRole('listitem')
  expect(screen.queryByText('third wording')).not.toBeInTheDocument() // hidden until shown
  expect(screen.queryByText('first wording')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תוכן' }))
  const items = await screen.findAllByRole('listitem')
  expect(items.map((i) => i.textContent)).toEqual([
    expect.stringContaining('third wording'),
    expect.stringContaining('second wording'),
    expect.stringContaining('first wording'),
  ])
  expect(items[0]).toHaveTextContent('הנוכחי')
  expect(items[1]).toHaveTextContent('גרסה קודמת')
  expect(items[2]).toHaveTextContent('מקורי')
  expect(dialog).toBeInTheDocument()
})

test('a redacted message shows no earlier wording', async () => {
  const redacted = { ...detail, text: null, redacted: true, revisions: [] }
  renderWithApp(<MessageFlags m={{ ...base, edited_at: detail.edited_at }} history />, {
    '/api/messages/7': redacted,
  })
  await userEvent.click(screen.getByRole('button', { name: /הצגת היסטוריית העריכה/ }))
  expect(await screen.findByText(/אין נוסח קודם שמור/)).toBeInTheDocument()
  expect(screen.queryByText('first wording')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /הצגת תוכן/ })).not.toBeInTheDocument()
})

test('closing the edit history hides the wordings again', async () => {
  renderWithApp(<MessageFlags m={{ ...base, edited_at: detail.edited_at }} history />, {
    '/api/messages/7': detail,
  })
  await userEvent.click(screen.getByRole('button', { name: /הצגת היסטוריית העריכה/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'הצגת תוכן' }))
  expect(await screen.findByText('third wording')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'סגירה' }))
  await userEvent.click(screen.getByRole('button', { name: /הצגת היסטוריית העריכה/ }))
  await screen.findByRole('button', { name: 'הצגת תוכן' })
  expect(screen.queryByText('third wording')).not.toBeInTheDocument()
})
