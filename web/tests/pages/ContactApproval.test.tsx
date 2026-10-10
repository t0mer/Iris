import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'
import { ContactApproval } from '../../src/pages/ContactApproval'

test('approval requires a deliberate confirmation, not opening the link', async () => {
  const fetch = vi.fn(
    async (_path: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ channel: 'email' }), { status: 200 }),
  )
  vi.stubGlobal('fetch', fetch)
  render(
    <MemoryRouter initialEntries={['/verify-contact?token=secret']}>
      <ContactApproval />
    </MemoryRouter>,
  )
  expect(fetch).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Approve contact' }))
  expect(
    await screen.findByText(/Your contact is approved for alerts and two-factor authentication/),
  ).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0]?.[0]).toBe('/api/auth/confirm-contact')
})
