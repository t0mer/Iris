import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ParentConnections } from '../../src/components/PhoneConnections'
import { renderWithApp } from '../test-utils'

test.each(['smtp', 'openwa', 'greenapi'] as const)(
  '%s recipients do not show duplicate email or Telegram destinations',
  async (channel) => {
    renderWithApp(<ParentConnections showSender={false} channel={channel} />, {
      '/api/settings': {
        'alerts.recipient': 'email:parent@example.com',
        'alerts.channel': 'telegram',
      },
      '/api/instances': [],
      '/api/users': [],
    })
    await screen.findByText('email:parent@example.com')
    expect(screen.queryByPlaceholderText('Parent email for alerts')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Telegram chat ID for/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Save.*destination/ })).not.toBeInTheDocument()
  },
)

test('Telegram recipients can save their chat ID without changing child assignments', async () => {
  const calls = renderWithApp(<ParentConnections showSender={false} channel="telegram" />, {
    '/api/settings': { 'alerts.recipient': 'email:parent@example.com', 'alerts.channel': 'smtp' },
    '/api/instances': [],
    '/api/users': [],
  })
  await userEvent.type(await screen.findByLabelText(/Telegram chat ID for/), '1234')
  await userEvent.click(screen.getByRole('button', { name: 'Save Telegram destination' }))
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: 'PUT',
      url: '/api/settings',
      body: {
        settings: {
          'alerts.recipient_contacts': {
            'email:parent@example.com': { telegram_chat_id: '1234' },
          },
        },
      },
    }),
  )
})

test('choosing a parent by account email does not select SMTP or require email approval', async () => {
  const calls = renderWithApp(<ParentConnections showSender={false} channel="greenapi" />, {
    '/api/settings': { 'alerts.recipient': null },
    '/api/instances': [],
    '/api/users': [
      {
        id: 2,
        username: 'Parent',
        role: 'parent',
        email: 'parent@example.com',
        email_verified: false,
        whatsapp_number: null,
      },
    ],
  })
  await userEvent.selectOptions(
    await screen.findByLabelText('Choose a parent'),
    'parent@example.com',
  )
  await waitFor(() =>
    expect(
      calls.some(
        (call) => call.method === 'PUT' && JSON.stringify(call.body).includes('parent@example.com'),
      ),
    ).toBe(true),
  )
})
