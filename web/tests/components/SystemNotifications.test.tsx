import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SystemNotifications } from '../../src/components/SystemNotifications'
import { renderWithApp } from '../test-utils'

test('system notices save independent recipients and channel without editing parent settings', async () => {
  const calls = renderWithApp(
    <SystemNotifications settings={{ 'alerts.recipient': 'email:parent@example.com' }} />,
    {
      '/api/users': [
        {
          id: 1,
          username: 'Admin',
          role: 'admin',
          email: 'admin@example.com',
          whatsapp_number: null,
        },
      ],
      '/api/settings/recipient-channels': {
        channels: [{ channel: 'telegram', configured: true, recipients: [] }],
      },
      '/api/settings': {},
    },
  )
  await userEvent.click(await screen.findByRole('checkbox', { name: 'Admin' }))
  await userEvent.click(screen.getByRole('radio', { name: 'Telegram bot' }))
  await userEvent.type(screen.getByLabelText('Telegram chat ID'), '123456')
  await userEvent.click(screen.getByRole('button', { name: 'Save system notifications' }))
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: 'PUT',
      url: '/api/settings',
      body: {
        settings: {
          'alerts.system_recipient': 'email:admin@example.com',
          'alerts.system_contacts': { 'email:admin@example.com': { telegram_chat_id: '123456' } },
          'alerts.provider_notification_channel': 'telegram',
        },
      },
    }),
  )
  expect(await screen.findByRole('status')).toHaveTextContent('System notification settings saved.')
})
