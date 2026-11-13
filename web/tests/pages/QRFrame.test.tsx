import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { QRFrame } from '../../src/pages/QRFrame'
import { renderWithApp } from '../test-utils'

const renderFrame = (body: Record<string, unknown>) =>
  renderWithApp(
    <Routes>
      <Route path="/pairing/qr/:id" element={<QRFrame />} />
    </Routes>,
    body,
    '/pairing/qr/6',
  )

test('QR frame fetches provider image through the protected Iris endpoint', async () => {
  const calls = renderFrame({
    '/api/instances/6/qr': { status: 'qr_ready', qr: 'data:image/png;base64,iVBORw0KGgo=' },
  })
  expect(await screen.findByRole('img', { name: 'WhatsApp QR code' })).toHaveAttribute(
    'src',
    'data:image/png;base64,iVBORw0KGgo=',
  )
  expect(calls.every((call) => !call.url.includes('api-key') && !call.url.includes('openwa'))).toBe(
    true,
  )
  fireEvent.error(screen.getByRole('img'))
  expect(screen.getByRole('status')).toHaveTextContent('This QR code is no longer valid.')
  expect(screen.getByRole('button', { name: 'Request a new QR code' })).toBeEnabled()
})

test('expired QR is hidden and requesting a replacement never deletes a phone', async () => {
  const calls = renderFrame({ '/api/instances/6/qr': { status: 'expired', qr: null } })
  expect(
    await screen.findByText('This QR code is no longer valid. Request a new code.'),
  ).toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Request a new QR code' }))
  expect(
    calls.some((call) => call.method === 'POST' && call.url === '/api/instances/6/qr/refresh'),
  ).toBe(true)
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
})
