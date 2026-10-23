import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  getShowContentByDefault,
  setShowContentByDefault,
  useShowContentByDefault,
} from '../../src/lib/prefs'
import { useReveal } from '../../src/lib/useReveal'
import { Concealed, RevealButton } from '../../src/components/Reveal'

function Item({ id = '1' }: { id?: string }) {
  const { revealed, toggle } = useReveal(id)
  return (
    <>
      <RevealButton revealed={revealed} onToggle={toggle} />
      <p>
        <Concealed revealed={revealed}>text of {id}</Concealed>
      </p>
    </>
  )
}

function Flag() {
  return <span>{useShowContentByDefault() ? 'on' : 'off'}</span>
}

afterEach(() => {
  localStorage.clear()
  act(() => setShowContentByDefault(false))
  vi.restoreAllMocks()
})

test('content starts hidden when the preference was never set', () => {
  render(<Item />)
  expect(screen.queryByText('text of 1')).not.toBeInTheDocument()
  expect(getShowContentByDefault()).toBe(false)
})

test('with the preference on, content starts shown and the eye still hides it', async () => {
  setShowContentByDefault(true)
  render(<Item />)
  expect(screen.getByText('text of 1')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Hide content' }))
  expect(screen.queryByText('text of 1')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(screen.getByText('text of 1')).toBeInTheDocument()
})

test('showing one item does not change the preference', async () => {
  render(<Item />)
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(getShowContentByDefault()).toBe(false)
})

test('the preference is remembered across page loads', () => {
  setShowContentByDefault(true)
  expect(localStorage.getItem('iris-show-content')).toBe('1')
  const first = render(<Item />)
  first.unmount()
  render(<Item />)
  expect(screen.getByText('text of 1')).toBeInTheDocument()
})

test('turning it off again hides everything that has not been toggled', () => {
  setShowContentByDefault(true)
  render(
    <>
      <Flag />
      <Item />
    </>,
  )
  expect(screen.getByText('text of 1')).toBeInTheDocument()
  act(() => setShowContentByDefault(false))
  expect(screen.getByText('off')).toBeInTheDocument()
  expect(screen.queryByText('text of 1')).not.toBeInTheDocument()
})

test('an item the owner toggled keeps its choice when the preference changes', async () => {
  render(<Item />)
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  act(() => setShowContentByDefault(false))
  expect(screen.getByText('text of 1')).toBeInTheDocument()
})

test('blocked storage falls back to hidden and still lets the switch work for this page', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  render(<Item />)
  expect(screen.queryByText('text of 1')).not.toBeInTheDocument()
  act(() => setShowContentByDefault(true))
  expect(screen.getByText('text of 1')).toBeInTheDocument()
})

test('another tab turning it off hides this one too', () => {
  setShowContentByDefault(true)
  render(<Item />)
  expect(screen.getByText('text of 1')).toBeInTheDocument()
  act(() => {
    localStorage.removeItem('iris-show-content')
    window.dispatchEvent(new StorageEvent('storage', { key: 'iris-show-content' }))
  })
  expect(screen.queryByText('text of 1')).not.toBeInTheDocument()
})

test('after a blocked write, turning it off again really turns it off', () => {
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('quota')
  })
  act(() => setShowContentByDefault(true))
  expect(getShowContentByDefault()).toBe(true)
  spy.mockRestore()
  act(() => setShowContentByDefault(false))
  expect(getShowContentByDefault()).toBe(false)
})
