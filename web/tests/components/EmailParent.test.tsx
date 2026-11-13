import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ParentConnections } from '../../src/components/PhoneConnections'
import { renderWithApp } from '../test-utils'

const target = 'email:parent@example.com'
const row = {
  target,
  user_id: 2,
  name: 'Parent',
  eligible: true,
  reason: null,
  legacy: false,
  destination: '15550100101@c.us',
  channel: 'greenapi',
}
const options = {
  channels: [
    { channel: 'greenapi', configured: true, recipients: [row] },
    {
      channel: 'smtp',
      configured: true,
      recipients: [{ ...row, channel: 'smtp', destination: 'parent@example.com' }],
    },
    {
      channel: 'telegram',
      configured: true,
      recipients: [{ ...row, channel: 'telegram', eligible: false, destination: null }],
    },
    { channel: 'openwa', configured: false, recipients: [] },
  ],
}
const routes = {
  '/api/settings': {
    'alerts.recipient': target,
    'alerts.channel': 'greenapi',
    'alerts.recipient_channels': { [target]: 'greenapi' },
  },
  '/api/instances': [],
  '/api/users': [
    {
      id: 2,
      username: 'Parent',
      role: 'parent',
      email: 'parent@example.com',
      email_verified: true,
      whatsapp_number: '+15550100101',
    },
  ],
  '/api/settings/alert-readiness': { recipients: [row] },
  '/api/settings/recipient-channels': options,
}

test('GreenAPI displays the actual WhatsApp destination instead of an email identity', async () => {
  renderWithApp(<ParentConnections showSender={false} />, routes)
  expect(await screen.findByText('+15550100101')).toBeVisible()
  expect(screen.queryByText(target)).not.toBeInTheDocument()
  expect(
    within(screen.getByRole('group', { name: 'Alert channel · Parent' })).getByRole('radio', {
      name: 'WhatsApp via GreenAPI',
    }),
  ).toBeChecked()
  expect(screen.queryByPlaceholderText('Parent email for alerts')).not.toBeInTheDocument()
})

test('editing a parent channel preserves recipient identity and child assignments', async () => {
  const calls = renderWithApp(<ParentConnections showSender={false} />, routes)
  await userEvent.click(
    within(await screen.findByRole('group', { name: 'Alert channel · Parent' })).getByRole(
      'radio',
      { name: 'Email via SMTP' },
    ),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Save channel' }))
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: 'PUT',
      url: '/api/settings',
      body: {
        settings: {
          'alerts.recipient': target,
          'alerts.recipient_channels': { [target]: 'smtp' },
          'alerts.recipient_contacts': {},
          'alerts.recipient_children': {},
        },
      },
    }),
  )
})

test('Telegram destination and channel are saved together', async () => {
  const calls = renderWithApp(<ParentConnections showSender={false} />, routes)
  await userEvent.click(
    within(await screen.findByRole('group', { name: 'Alert channel · Parent' })).getByRole(
      'radio',
      { name: 'Telegram bot' },
    ),
  )
  await userEvent.type(screen.getByLabelText('Telegram chat ID'), '1234')
  await userEvent.click(screen.getByRole('button', { name: 'Save channel' }))
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: 'PUT',
      url: '/api/settings',
      body: {
        settings: {
          'alerts.recipient': target,
          'alerts.recipient_channels': { [target]: 'telegram' },
          'alerts.recipient_contacts': { [target]: { telegram_chat_id: '1234' } },
          'alerts.recipient_children': {},
        },
      },
    }),
  )
})

test('adding a parent requires an explicit configured channel and does not add on account selection', async () => {
  const calls = renderWithApp(<ParentConnections showSender={false} />, {
    ...routes,
    '/api/settings': { 'alerts.recipient': null, 'alerts.channel': 'greenapi' },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Add parent' }))
  await userEvent.selectOptions(
    await screen.findByLabelText('Choose a parent'),
    'parent@example.com',
  )
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
  expect(screen.getByRole('button', { name: 'Add parent' })).toBeDisabled()
  const picker = screen.getByRole('group', { name: 'Alert channel' })
  expect(within(picker).queryByRole('radio', { name: /OpenWA/ })).not.toBeInTheDocument()
  await userEvent.click(within(picker).getByRole('radio', { name: 'WhatsApp via GreenAPI' }))
  await userEvent.click(screen.getByRole('button', { name: 'Add parent' }))
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: 'PUT',
      url: '/api/settings',
      body: {
        settings: {
          'alerts.recipient': 'parent@example.com',
          'alerts.recipient_channels': { [target]: 'greenapi' },
          'alerts.recipient_contacts': {},
          'alerts.recipient_children': {},
        },
      },
    }),
  )
})

test('incompatible and unconfigured channels are hidden and a missing setup is explained', async () => {
  renderWithApp(<ParentConnections showSender={false} />, {
    ...routes,
    '/api/settings': { 'alerts.recipient': null },
    '/api/settings/recipient-channels': {
      channels: options.channels.map((option) => ({
        ...option,
        configured: option.channel === 'greenapi',
        recipients: [{ ...row, eligible: false }],
      })),
    },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Add parent' }))
  await userEvent.selectOptions(
    await screen.findByLabelText('Choose a parent'),
    'parent@example.com',
  )
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'No configured channel is available for this parent',
  )
  expect(screen.getByRole('group', { name: 'Alert channel' })).toBeDisabled()
})

test('a rejected channel save is visible and keeps the existing setting', async () => {
  renderWithApp(<ParentConnections showSender={false} />, routes)
  await screen.findByText('+15550100101')
  const original = fetch
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) =>
      init?.method === 'PUT'
        ? Promise.resolve(
            new Response(JSON.stringify({ detail: 'Save and test SMTP first.' }), { status: 422 }),
          )
        : original(url, init),
    ),
  )
  await userEvent.click(
    within(screen.getByRole('group', { name: 'Alert channel · Parent' })).getByRole('radio', {
      name: 'Email via SMTP',
    }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Save channel' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save and test SMTP first.')
  expect(screen.getByText('+15550100101')).toBeVisible()
})
