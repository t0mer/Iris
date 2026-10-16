import { he } from '../lib/he'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { RepairPhone } from './RepairPhone'
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
  await userEvent.click(screen.getByRole('button', { name: he('Re-pair WhatsApp') }))
  expect(
    await screen.findByRole('img', { name: he('WhatsApp re-pairing QR code') }),
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: he('Close') }))
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
})
test('ready session restores webhook without creating another phone', async () => {
  const calls = renderWithApp(<RepairPhone phone={phone} />, {
    '/api/instances/3/re-pair': { status: 'ready', qr: null },
    '/api/instances/3/register-webhook': { webhook_id: 'existing-hook' },
  })
  await userEvent.click(screen.getByRole('button', { name: he('Re-pair WhatsApp') }))
  expect(await screen.findByText('Example child reconnected.')).toBeInTheDocument()
  expect(
    calls.some(
      (call) => call.url === '/api/instances/3/register-webhook' && call.method === 'POST',
    ),
  ).toBe(true)
  expect(calls.some((call) => call.url === '/api/instances' && call.method === 'POST')).toBe(false)
})
