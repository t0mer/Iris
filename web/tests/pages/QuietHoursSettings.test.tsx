import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QuietHoursSettings } from '../../src/pages/QuietHoursSettings'
import { renderWithApp } from '../test-utils'

test('quiet hours are disabled by default and parent and system scopes save separately', async () => {
  const calls = renderWithApp(<QuietHoursSettings settings={{}} />, { '/api/settings': {} })
  const parents = screen.getByRole('group', { name: 'Parent notifications' })
  const system = screen.getByRole('group', { name: 'System notifications' })
  expect(within(parents).getByRole('checkbox')).not.toBeChecked()
  expect(within(system).getByRole('checkbox')).not.toBeChecked()
  expect(within(parents).getByLabelText('Quiet hours start')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Save quiet hours' })).toBeDisabled()
  await userEvent.click(within(parents).getByRole('checkbox'))
  expect(within(parents).getByLabelText('Quiet hours start')).toBeEnabled()
  expect(within(system).getByLabelText('Quiet hours start')).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Save quiet hours' }))
  await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
  const saved = calls.find((c) => c.method === 'PUT')!.body
  expect(saved).toEqual({
    settings: {
      'alerts.parent_quiet_hours': { enabled: true, start: '22:00', end: '07:00' },
      'alerts.system_quiet_hours': { enabled: false, start: '22:00', end: '07:00' },
    },
  })
})

test('cancel restores the stored quiet-hour settings', async () => {
  renderWithApp(<QuietHoursSettings settings={{}} />, {})
  const checkbox = within(screen.getByRole('group', { name: 'System notifications' })).getByRole(
    'checkbox',
  )
  await userEvent.click(checkbox)
  expect(checkbox).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(checkbox).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Save quiet hours' })).toBeDisabled()
})
