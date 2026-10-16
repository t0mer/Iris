import { he } from '../lib/he'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InstallApp } from './InstallApp'

test('offers installation guidance when a native prompt is unavailable', async () => {
  render(<InstallApp />)
  await userEvent.click(screen.getByRole('button', { name: he('Install app') }))
  expect(screen.getByRole('dialog', { name: he('Install Iris') })).toBeInTheDocument()
  expect(screen.getByText(/ב־Chrome ב־Android/)).toBeInTheDocument()
  expect(screen.getByText(/התראות ברקע/)).toBeInTheDocument()
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
  await userEvent.click(screen.getByRole('button', { name: he('Install app') }))
  fireEvent.click(screen.getByRole('button', { name: he('Install Iris') }))
  expect(prompt).toHaveBeenCalledOnce()
})
