import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InstallApp } from '../../src/components/InstallApp'

beforeEach(() => localStorage.removeItem('iris.app-installed'))

test('hides the install button after installation and remembers it on reload', () => {
  const first = render(<InstallApp />)
  act(() => window.dispatchEvent(new Event('appinstalled')))
  expect(screen.queryByRole('button', { name: /app/i })).not.toBeInTheDocument()
  first.unmount()
  render(<InstallApp />)
  expect(screen.queryByRole('button', { name: /app/i })).not.toBeInTheDocument()
})

test('offers installation guidance when a native prompt is unavailable', async () => {
  render(<InstallApp />)
  await userEvent.click(screen.getByRole('button', { name: 'Install app' }))
  expect(screen.getByRole('dialog', { name: 'Install Iris' })).toBeInTheDocument()
  expect(screen.getByText(/In Chrome on Android/)).toBeInTheDocument()
  expect(screen.getByText(/background notifications/)).toBeInTheDocument()
})

test('uses the browser installation prompt only after a click', async () => {
  render(<InstallApp compact />)
  const prompt = vi.fn().mockResolvedValue(undefined)
  const event = Object.assign(new Event('beforeinstallprompt', { cancelable: true }), {
    prompt,
    userChoice: Promise.resolve({ outcome: 'accepted' }),
  })
  act(() => {
    window.dispatchEvent(event)
  })
  expect(event.defaultPrevented).toBe(true)
  expect(prompt).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Install app' }))
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Install Iris' }))
    await event.userChoice
  })
  expect(prompt).toHaveBeenCalledOnce()
})
