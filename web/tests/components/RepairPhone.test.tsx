import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { RepairPhone } from '../../src/components/RepairPhone'
const phone = {
  id: 3,
  kid_name: 'Example child',
  role: 'child' as const,
  enabled: true,
  phone_number: null,
  openwa_base_url: 'https://wa.example',
  openwa_instance_id: 'existing-id',
  api_key_set: true,
  webhook_url: 'https://iris.example/webhook',
  last_webhook_at: null,
  created_at: '2026-10-08T18:00:00Z',
}
test('re-pair shows QR for the existing phone and closing never deletes it', async () => {
  const calls = renderWithApp(<RepairPhone phone={phone} />, {
    '/api/instances/3/re-pair': { status: 'qr_ready', qr: 'data:image/png;base64,iVBORw0KGgo=' },
  })
  await userEvent.click(screen.getByRole('button', { name: 'Re-pair WhatsApp' }))
  expect(await screen.findByTitle('WhatsApp QR code')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
})
test('ready session restores webhook without creating another phone', async () => {
  const calls = renderWithApp(<RepairPhone phone={phone} />, {
    '/api/instances/3/re-pair': { status: 'ready', qr: null },
    '/api/instances/3/register-webhook': { webhook_id: 'existing-hook' },
  })
  await userEvent.click(screen.getByRole('button', { name: 'Re-pair WhatsApp' }))
  expect((await screen.findAllByText('Example child reconnected.')).length).toBeGreaterThan(0)
  expect(
    calls.some(
      (call) => call.url === '/api/instances/3/register-webhook' && call.method === 'POST',
    ),
  ).toBe(true)
  expect(calls.some((call) => call.url === '/api/instances' && call.method === 'POST')).toBe(false)
})

test('connected phones hide re-pair and do not start a repair request', () => {
  const calls = renderWithApp(<RepairPhone phone={{ ...phone, connection_status: 'ready' }} />, {})
  expect(screen.queryByRole('button', { name: 'Re-pair WhatsApp' })).not.toBeInTheDocument()
  expect(calls).toHaveLength(0)
})

test('disconnected phones offer re-pair', () => {
  renderWithApp(<RepairPhone phone={{ ...phone, connection_status: 'disconnected' }} />, {})
  expect(screen.getByRole('button', { name: 'Re-pair WhatsApp' })).toBeInTheDocument()
})

test('successful pairing with failed monitoring shows connected state and can retry', async () => {
  let attempts = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/re-pair'))
        return new Response(JSON.stringify({ status: 'ready', qr: null }), { status: 200 })
      if (url.endsWith('/register-webhook') && attempts++ === 0)
        return new Response(
          JSON.stringify({ detail: 'OpenWA: Destination address is not allowed' }),
          { status: 502 },
        )
      return new Response(JSON.stringify({ webhook_id: 'existing-hook' }), { status: 200 })
    }),
  )
  // Use the normal provider wrapper, then replace its fetch stub before initiating pairing.
  const mockedFetch = globalThis.fetch
  renderWithApp(<RepairPhone phone={phone} />, {})
  vi.stubGlobal('fetch', mockedFetch)
  await userEvent.click(screen.getByRole('button', { name: 'Re-pair WhatsApp' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'WhatsApp connected successfully, but monitoring setup failed.',
  )
  expect(screen.getByRole('status')).toHaveTextContent(
    'WhatsApp connected. Monitoring setup needs attention.',
  )
  expect(screen.queryByText(/waiting for OpenWA to provide a QR/)).not.toBeInTheDocument()
  expect(screen.getByRole('dialog', { name: 'Example child connected' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry restoring monitoring' }))
  expect((await screen.findAllByText('Example child reconnected.')).length).toBeGreaterThan(0)
  expect(attempts).toBe(2)
})
