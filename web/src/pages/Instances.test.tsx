import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Instances } from './Instances'

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

test('shows each phone with its webhook address and says when nothing has arrived yet', async () => {
  renderWithApp(<Instances />, { '/api/instances': [phone] })
  expect(await screen.findByText('Noa')).toBeInTheDocument()
  expect(screen.getByLabelText('Webhook address')).toHaveValue(
    'https://iris.example.com/webhooks/abc',
  )
  expect(screen.getByText('Nothing received yet')).toBeInTheDocument()
})

test('adding a phone asks for labelled fields and posts them', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [] })
  expect(await screen.findByText('No phones yet')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: /Add a phone/ })[0])
  const dialog = await screen.findByRole('dialog', { name: 'Add a phone' })
  const d = within(dialog)
  await userEvent.type(d.getByLabelText("Child's name"), 'Dan')
  await userEvent.type(d.getByLabelText('OpenWA address'), 'https://wa.example.com')
  await userEvent.type(d.getByLabelText(/OpenWA session ID/), 'sess-1')
  await userEvent.type(d.getByLabelText('OpenWA API key'), 'secret')
  await userEvent.click(d.getByRole('button', { name: 'Add phone' }))
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
  await userEvent.click(await screen.findByRole('button', { name: /Remove/ }))
  const confirm = await screen.findByRole('alertdialog', { name: 'Remove Noa?' })
  expect(within(confirm).getByText(/stops watching this phone/)).toBeInTheDocument()
  await userEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }))
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: /Remove/ }))
  await userEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove phone' }),
  )
  expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/instances/4')).toBe(true)
})

test('pausing a phone sends enabled false and confirms what changed', async () => {
  const calls = renderWithApp(<Instances />, { '/api/instances': [phone] })
  await userEvent.click(await screen.findByRole('switch', { name: 'Watch Noa' }))
  expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({
    url: '/api/instances/4',
    body: { enabled: false },
  })
  expect(await screen.findByText('Paused watching Noa.')).toBeInTheDocument()
})
