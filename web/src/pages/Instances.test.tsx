import { he } from '../lib/he'
import { screen, within, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Instances } from './Instances'
import { ParentConnections } from '../components/PhoneConnections'

const phone = {
  id: 4,
  kid_name: 'Noa',
  phone_number: null,
  openwa_base_url: 'https://wa.example.com',
  openwa_instance_id: '11111111-aaaa',
  api_key_set: true,
  enabled: true,
  webhook_url: 'https://iris.example.com/webhooks/abc',
  last_webhook_at: null,
  created_at: '2026-10-01T00:00:00Z',
}

test('parent connections are separate and have no child monitoring controls', async () => {
  renderWithApp(<ParentConnections />, {
    '/api/instances': [
      phone,
      { ...phone, id: 5, kid_name: 'Example parent', role: 'parent', enabled: false },
    ],
    '/api/settings': { 'alerts.recipient': '15550100101, 15550100102' },
  })
  expect(await screen.findByText('Example parent')).toBeInTheDocument()
  expect(screen.queryByText('Noa')).not.toBeInTheDocument()
  expect(screen.queryByRole('switch', { name: 'Watch Example parent' })).not.toBeInTheDocument()
  expect(screen.getByText('+15550100101')).toBeInTheDocument()
  expect(screen.getByText('+15550100102')).toBeInTheDocument()
})

test('adding a parent recipient only saves the alert number', async () => {
  const calls = renderWithApp(<ParentConnections />, {
    '/api/instances': [],
    '/api/settings': { 'alerts.recipient': '15550100101' },
  })
  await userEvent.type(await screen.findByLabelText(he('Parent phone number')), '15550100102')
  await userEvent.click(screen.getByRole('button', { name: he('Add parent') }))
  expect(calls.find((call) => call.method === 'PUT')).toMatchObject({
    url: '/api/settings',
    body: { settings: { 'alerts.recipient': '15550100101, 15550100102' } },
  })
  expect(calls.some((call) => call.method === 'POST' && call.url === '/api/instances')).toBe(false)
})

test('shows each phone with its webhook address and says when nothing has arrived yet', async () => {
  renderWithApp(<Instances />, { '/api/instances': [phone] })
  expect(await screen.findByText('Noa')).toBeInTheDocument()
  expect(screen.getByLabelText('כתובת ה-webhook')).toHaveValue(
    'https://iris.example.com/webhooks/abc',
  )
  expect(screen.getByText('עדיין לא התקבלו הודעות')).toBeInTheDocument()
})

test('adding a phone asks for labelled fields and posts them', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [] })
  expect(await screen.findByText('אין עדיין טלפונים')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: /הוספת טלפון/ })[0])
  const dialog = await screen.findByRole('dialog', { name: 'הוספת טלפון' })
  const d = within(dialog)
  await userEvent.type(d.getByLabelText('שם הילד/ה'), 'Dan')
  await userEvent.type(d.getByLabelText('כתובת OpenWA'), 'https://wa.example.com')
  await userEvent.type(d.getByLabelText(/מזהה הסשן ב-OpenWA/), 'sess-1')
  await userEvent.type(d.getByLabelText('מפתח API של OpenWA'), 'secret')
  await userEvent.click(d.getByRole('button', { name: 'הוספת טלפון' }))
  expect(calls.find((c) => c.method === 'POST')).toMatchObject({
    url: '/api/instances',
    body: {
      kid_name: 'Dan',
      openwa_base_url: 'https://wa.example.com',
      openwa_instance_id: 'sess-1',
      openwa_api_key: 'secret',
      phone_number: null,
    },
  })
})

test('removing a phone needs a confirmation that names the consequence; cancel does nothing', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [phone] })
  await userEvent.click(await screen.findByRole('button', { name: /הסרה/ }))
  const confirm = await screen.findByRole('alertdialog', { name: 'להסיר את Noa?' })
  expect(within(confirm).getByText(/תפסיק לנטר את הטלפון/)).toBeInTheDocument()
  await userEvent.click(within(confirm).getByRole('button', { name: 'ביטול' }))
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: /הסרה/ }))
  await userEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'הסרת הטלפון' }),
  )
  expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/instances/4')).toBe(true)
})

test('pausing a phone sends enabled false and confirms what changed', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [phone] })
  await userEvent.click(await screen.findByRole('switch', { name: 'ניטור Noa' }))
  expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({
    url: '/api/instances/4',
    body: { enabled: false },
  })
  expect(await screen.findByText('הניטור של Noa הושהה.')).toBeInTheDocument()
})

test('Phones contains children and directs parents to Settings Alerts', async () => {
  renderWithApp(<Instances />, {
    '/api/instances': [phone, { ...phone, id: 5, kid_name: 'Parent sender', role: 'parent' }],
  })
  expect(await screen.findByText('Noa')).toBeInTheDocument()
  expect(screen.queryByText('Parent sender')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: he('Parents') })).not.toBeInTheDocument()
  expect(screen.getByText(/נמענים וחיבורים לשליחת התראות/)).toBeInTheDocument()
})

test('automatic pairing uses configured OpenWA and hides redundant fields', async () => {
  renderWithApp(<Instances />, {
    '/api/instances': [],
    '/api/pairing/config': { configured: true },
  })
  await userEvent.click(screen.getByRole('button', { name: he('Add a phone') }))
  await userEvent.click(await screen.findByRole('tab', { name: he('Automatic') }))
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.queryByLabelText(he('OpenWA address'))).not.toBeInTheDocument()
  expect(dialog.queryByLabelText(he('OpenWA API key'))).not.toBeInTheDocument()
  expect(dialog.queryByLabelText(he('OpenWA session ID'))).not.toBeInTheDocument()
  expect(dialog.queryByLabelText(he('Phone number (optional)'))).not.toBeInTheDocument()
  expect(dialog.queryByRole('textbox', { name: /Child's name/ })).not.toBeInTheDocument()
  expect(dialog.getByRole('button', { name: he('Get pairing QR') })).toBeEnabled()
})

test('automatic tab is hidden when server OpenWA configuration is missing', async () => {
  renderWithApp(<Instances />, {
    '/api/instances': [],
    '/api/pairing/config': { configured: false },
  })
  await userEvent.click(screen.getByRole('button', { name: he('Add a phone') }))
  expect(screen.queryByRole('tab', { name: he('Automatic') })).not.toBeInTheDocument()
})

test('OpenWA deletion is unchecked by default and sent only when selected', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [phone] })
  await userEvent.click(await screen.findByRole('button', { name: /הסרה/ }))
  const checkbox = screen.getByRole('checkbox', { name: /מחיקת החיבור גם ב־OpenWA/ })
  expect(checkbox).not.toBeChecked()
  await userEvent.click(checkbox)
  await userEvent.click(screen.getByRole('button', { name: he('Remove phone') }))
  expect(
    calls.some(
      (call) =>
        call.method === 'POST' && call.url === '/api/instances/4/remove-openwa?stage=deactivate',
    ),
  ).toBe(true)
})

test('selected child-role alert sender remains removable under Alerts', async () => {
  renderWithApp(<ParentConnections />, {
    '/api/instances': [{ ...phone, role: 'child' }],
    '/api/settings': { 'alerts.sender_instance_id': phone.id },
  })
  expect(await screen.findByText('Noa')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /הסרה/ })).toBeInTheDocument()
})

test('removal waits for each stage and retains the dialog for retry after failure', async () => {
  renderWithApp(<Instances />, { '/api/instances': [phone] })
  await userEvent.click(await screen.findByRole('button', { name: /הסרה/ }))
  await userEvent.click(screen.getByRole('checkbox', { name: /מחיקת החיבור גם/ }))
  const originalFetch = globalThis.fetch
  let finishLogout!: (response: Response) => void
  let finishDelete!: (response: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('stage=deactivate'))
        return new Promise<Response>((resolve) => {
          finishLogout = resolve
        })
      if (url.includes('stage=delete'))
        return new Promise<Response>((resolve) => {
          finishDelete = resolve
        })
      return originalFetch(url, init)
    }),
  )
  await userEvent.click(screen.getByRole('button', { name: he('Remove phone') }))
  expect(await screen.findByText(he('Deactivating WhatsApp…'))).toBeInTheDocument()
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
  expect(screen.getByRole('button', { name: he('Cancel') })).toBeDisabled()
  await act(async () => finishLogout(new Response(null, { status: 204 })))
  expect(await screen.findByText(he('Deleting the OpenWA session…'))).toBeInTheDocument()
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '1')
  await act(async () =>
    finishDelete(
      new Response(JSON.stringify({ detail: he('OpenWA unavailable') }), { status: 502 }),
    ),
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('אפשר לנסות להסיר שוב')
  expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  await waitFor(() =>
    expect(screen.getByRole('button', { name: he('Remove phone') })).toBeEnabled(),
  )
})

test('successful QR pairing saves automatically and name is a later optional step', async () => {
  const calls = renderWithApp(<Instances />, {
    '/api/instances': [],
    '/api/pairing/config': { configured: true },
    '/api/pairing': {
      token: 'draft-token',
      session_id: 'draft-id',
      status: 'ready',
      session_name: 'iris-draft-example',
      qr: null,
    },
    '/api/pairing/draft-token/complete': {
      ...phone,
      id: 8,
      kid_name: 'iris-draft-example',
      role: 'child',
    },
  })
  await userEvent.click(screen.getByRole('button', { name: he('Add a phone') }))
  await userEvent.click(await screen.findByRole('tab', { name: he('Automatic') }))
  expect(screen.queryByRole('button', { name: he('Add phone') })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: he('Get pairing QR') }))
  expect(await screen.findByRole('dialog', { name: he('Phone connected') })).toBeInTheDocument()
  expect(
    calls.filter(
      (call) => call.method === 'POST' && call.url === '/api/pairing/draft-token/complete',
    ),
  ).toHaveLength(1)
  expect(
    calls.some((call) => call.method === 'DELETE' && call.url === '/api/pairing/draft-token'),
  ).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: he('Close') }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(
    calls.some((call) => call.method === 'DELETE' && call.url === '/api/pairing/draft-token'),
  ).toBe(false)
})

test('edit phone exposes all connection fields and saves the Iris session label', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [phone] })
  await userEvent.click(await screen.findByRole('button', { name: he('Edit phone') }))
  const d = within(screen.getByRole('dialog', { name: 'עריכת Noa' }))
  expect(d.getByLabelText(/^שם לתצוגה$/)).toHaveValue('Noa')
  expect(d.getByLabelText(/כתובת OpenWA/)).toHaveValue(phone.openwa_base_url)
  expect(d.getByLabelText(/מזהה הסשן ב-OpenWA/)).toHaveValue(phone.openwa_instance_id)
  expect(d.getByLabelText(/מפתח API של OpenWA/)).toHaveValue('')
  expect(d.getByLabelText(/מספר טלפון/)).toBeInTheDocument()
  expect(d.getByLabelText(/תפקיד הטלפון/)).toBeInTheDocument()
  await userEvent.type(d.getByLabelText(/שם החיבור באיריס/), 'Family label')
  await userEvent.click(d.getByRole('button', { name: he('Save changes') }))
  expect(calls.find((call) => call.method === 'PATCH')).toMatchObject({
    body: { session_name: 'Family label', verify_openwa: false },
  })
})

test('enabled monitoring never hides a WhatsApp session requiring re-pairing', async () => {
  renderWithApp(<Instances />, {
    '/api/instances': [
      { ...phone, connection_status: 'qr_ready', connection_checked_at: '2026-10-08T18:00:00Z' },
    ],
  })
  expect(await screen.findByText(he('WhatsApp needs re-pairing'))).toBeInTheDocument()
  expect(screen.getByText(he('Monitoring enabled'))).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('לא ניתן לבדוק הודעות חדשות')
  expect(screen.getByRole('button', { name: he('Check connection') })).toBeInTheDocument()
})

test('Phones excludes the selected alert sender even with a legacy child role', async () => {
  renderWithApp(<Instances />, {
    '/api/instances': [phone, { ...phone, id: 5, kid_name: 'Legacy sender', role: 'child' }],
    '/api/settings': { 'alerts.sender_instance_id': 5 },
  })
  expect(await screen.findByText('Noa')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText('Legacy sender')).not.toBeInTheDocument())
})
