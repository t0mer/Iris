import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { UserSettings } from '../../src/pages/UserSettings'
import { NotificationsSettings } from '../../src/pages/NotificationsSettings'

const config = { smtp: {}, password_set: false, enabled: false }
const admin = { id: 1, username: 'admin', role: 'admin', email: null, whatsapp_number: null }

test('clearing the optional personal number submits null without changing other contacts', async () => {
  const calls = renderWithApp(<UserSettings />, {
    '/api/users/security/config': config,
    '/api/users': [{ ...admin, email: 'admin@example.com', whatsapp_number: '+15550100102' }],
    '/api/settings': {},
    '/api/settings/alert-readiness': { users: [] },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  await userEvent.clear(screen.getByRole('textbox', { name: 'Personal WhatsApp number' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save user' }))
  await waitFor(() =>
    expect(
      calls.some(
        (call) =>
          call.url === '/api/users/1' &&
          call.method === 'PUT' &&
          (call.body as { whatsapp_number?: string | null }).whatsapp_number === null,
      ),
    ).toBe(true),
  )
})

test('recipient status links to Notifications and OpenWA can request WhatsApp approval', async () => {
  const calls = renderWithApp(<UserSettings />, {
    '/api/users/security/config': config,
    '/api/users': [{ ...admin, whatsapp_number: '+15550100102' }],
    '/api/settings': { 'alerts.sender_instance_id': 2 },
    '/api/settings/alert-readiness': {
      users: [
        { id: 1, selected: false, eligible: false, reason: 'Not selected as an alert recipient.' },
      ],
    },
  })
  expect(
    await screen.findByRole('link', { name: 'Alerts: Not selected as an alert recipient.' }),
  ).toHaveAttribute('href', '/settings?tab=Notifications#parent-alert-recipients')
  const request = screen.getByRole('button', { name: 'Send WhatsApp approval for admin' })
  await waitFor(() => expect(request).toBeEnabled())
  await userEvent.click(request)
  await waitFor(() =>
    expect(
      calls.some(
        (c) =>
          c.url === '/api/users/1/approve-contact' &&
          JSON.stringify(c.body) === '{"channel":"whatsapp"}',
      ),
    ).toBe(true),
  )
})

test('2FA stays disabled before providers and contacts are ready', async () => {
  renderWithApp(<UserSettings />, { '/api/users/security/config': config, '/api/users': [admin] })
  expect(await screen.findByRole('button', { name: 'Enable 2FA' })).toBeDisabled()
  expect(screen.queryByLabelText('SMTP host')).not.toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Watch only' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Sign-in verification' })).not.toBeInTheDocument()
})

test.each(['email', 'whatsapp', 'mixed'])('2FA accepts approved %s channels', async (channel) => {
  const enrolled =
    channel === 'email'
      ? { ...admin, email: 'admin@example.com', email_verified: true }
      : { ...admin, whatsapp_number: '+15551234567', whatsapp_verified: true }
  const users =
    channel === 'mixed'
      ? [
          enrolled,
          {
            ...admin,
            id: 2,
            username: 'parent',
            role: 'parent',
            email: 'parent@example.com',
            email_verified: true,
          },
        ]
      : [enrolled]
  const calls = renderWithApp(<UserSettings />, {
    '/api/users/security/config': {
      ...config,
      smtp: { verified: channel !== 'whatsapp' },
      green_api: { verified: channel !== 'email' },
    },
    '/api/users': users,
  })
  const enable = await screen.findByRole('button', { name: 'Enable 2FA' })
  await waitFor(() => expect(enable).toBeEnabled())
  await userEvent.click(enable)
  await waitFor(() =>
    expect(
      calls.some((c) => c.url === '/api/users/security/two-factor' && c.method === 'PUT'),
    ).toBe(true),
  )
})

test('editing a user clearly labels admin password reset and personal WhatsApp', async () => {
  renderWithApp(<UserSettings />, { '/api/users/security/config': config, '/api/users': [admin] })
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  expect(screen.getByLabelText('Reset this user’s password (optional)')).toBeInTheDocument()
  expect(screen.getByLabelText('Personal WhatsApp number')).toBeInTheDocument()
  expect(screen.queryByText('OpenWA phone')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Delete admin/ })).not.toBeInTheDocument()
})

test('invalid user email has a readable error', async () => {
  renderWithApp(<UserSettings />, { '/api/users/security/config': config, '/api/users': [admin] })
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  await userEvent.type(screen.getByLabelText('Email'), 'invalid@gmail')
  await userEvent.click(screen.getByRole('button', { name: 'Save user' }))
  expect(await screen.findByRole('alert')).not.toHaveTextContent('[object Object]')
})

test('contact approval uses the user contact endpoint', async () => {
  const calls = renderWithApp(<UserSettings />, {
    '/api/users/security/config': { ...config, smtp: { verified: true } },
    '/api/users': [{ ...admin, email: 'admin@example.com', email_verified: false }],
  })
  await userEvent.click(
    await screen.findByRole('button', { name: 'Send email approval for admin' }),
  )
  await waitFor(() =>
    expect(calls.some((c) => c.url === '/api/users/1/approve-contact' && c.method === 'POST')).toBe(
      true,
    ),
  )
})

test('notifications supports generic SMTP and GreenAPI', async () => {
  renderWithApp(<NotificationsSettings />, { '/api/users/security/config': config })
  expect(await screen.findByRole('heading', { name: 'SMTP server' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /GreenAPI/ })).toBeInTheDocument()
  expect(
    screen.queryByRole('heading', { name: 'Two-factor authentication' }),
  ).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Sign-in verification' })).not.toBeInTheDocument()
})

test.each(['email', 'whatsapp'])(
  'sign-in channel lives under 2FA and offers only ready %s',
  async (channel) => {
    renderWithApp(<UserSettings />, {
      '/api/settings': { 'auth.default_channel': 'email' },
      '/api/users/security/config': {
        ...config,
        smtp: { verified: channel === 'email' },
        green_api: { verified: channel === 'whatsapp' },
      },
      '/api/users': [
        {
          ...admin,
          email: 'parent@example.com',
          email_verified: true,
          whatsapp_number: '+15550100101',
          whatsapp_verified: true,
        },
      ],
    })
    const heading = await screen.findByRole('heading', { name: 'Sign-in verification' })
    expect(heading.closest('section')).toHaveTextContent('Two-factor authentication')
    const select = screen.getByLabelText('Default sign-in code channel')
    expect(select).toHaveValue(channel)
    expect(select.querySelectorAll('option')).toHaveLength(1)
  },
)

test('sign-in channel stays hidden while a user lacks an approved contact', async () => {
  renderWithApp(<UserSettings />, {
    '/api/settings': {},
    '/api/users/security/config': { ...config, smtp: { verified: true } },
    '/api/users': [
      { ...admin, email: 'parent@example.com', email_verified: true },
      { ...admin, id: 2 },
    ],
  })
  expect(await screen.findByRole('button', { name: 'Enable 2FA' })).toBeDisabled()
  expect(screen.queryByLabelText('Default sign-in code channel')).not.toBeInTheDocument()
})

test('2FA sign-in preference saves independently from alert settings', async () => {
  const calls = renderWithApp(<UserSettings />, {
    '/api/settings': { 'auth.default_channel': 'email' },
    '/api/users/security/config': {
      ...config,
      smtp: { verified: true },
      green_api: { verified: true },
    },
    '/api/users': [
      {
        ...admin,
        email: 'parent@example.com',
        email_verified: true,
        whatsapp_number: '+15550100101',
        whatsapp_verified: true,
      },
    ],
  })
  await userEvent.selectOptions(
    await screen.findByLabelText('Default sign-in code channel'),
    'whatsapp',
  )
  await waitFor(() =>
    expect(
      calls.some(
        (call) =>
          call.url === '/api/settings' &&
          call.method === 'PUT' &&
          JSON.stringify(call.body) ===
            JSON.stringify({ settings: { 'auth.default_channel': 'whatsapp' } }),
      ),
    ).toBe(true),
  )
})

test.each([
  ['Test saved SMTP', '/api/users/security/smtp/test'],
  ['Test saved GreenAPI', '/api/users/security/whatsapp/test'],
])('failed %s result is shown as an error', async (button, endpoint) => {
  renderWithApp(<NotificationsSettings />, {
    '/api/users/security/config': { ...config, green_api_token_set: true },
    [endpoint]: { ok: false, detail: 'Provider test failed' },
  })
  await userEvent.click(await screen.findByRole('button', { name: button }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Provider test failed')
})
