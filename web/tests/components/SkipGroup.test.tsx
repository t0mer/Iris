import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SkipGroup } from '../../src/components/SkipGroup'
import { renderWithApp } from '../test-utils'

test('skips for a selected child and offers a separate history deletion confirmation', async () => {
  const children = [{ id: 4, kid_name: 'Noa', skipped: false }]
  const routes = {
    '/api/messages/7': { id: 7, chat_id: 3, is_group: true },
    '/api/messages/groups/3/children': children,
  }
  const calls = renderWithApp(<SkipGroup messageId={7} isGroup />, routes)
  await userEvent.click(await screen.findByRole('button', { name: 'Skip group' }))
  await userEvent.click(
    await within(screen.getByRole('dialog')).findByRole('button', { name: 'Skip group' }),
  )
  expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  const confirmation = await screen.findByRole('alertdialog')
  routes['/api/messages/groups/3/children'][0] = { id: 4, kid_name: 'Noa', skipped: true }
  await userEvent.click(within(confirmation).getByRole('button', { name: 'Skip group' }))
  await waitFor(() =>
    expect(calls.some((c) => c.method === 'PUT' && c.url.endsWith('/children/4'))).toBe(true),
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Delete history' }))
  expect(await screen.findByText('Delete group history for Noa?')).toBeInTheDocument()
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
})
