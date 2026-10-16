import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Concealed, Masked, RevealButton } from './Reveal'
import { useReveal } from '../lib/useReveal'

function Demo() {
  const { revealed, toggle } = useReveal()
  return (
    <>
      <RevealButton revealed={revealed} onToggle={toggle} />
      <p>
        <Concealed revealed={revealed} length={11}>
          secret text
        </Concealed>
      </p>
    </>
  )
}

test('starts hidden: the real text is not on the page, only a mask', () => {
  const { container } = render(<Demo />)
  expect(container).not.toHaveTextContent('secret')
  expect(screen.getByText('התוכן מוסתר')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'הצגת תוכן' })).toBeInTheDocument()
})

test('the eye shows and hides it again', async () => {
  render(<Demo />)
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תוכן' }))
  expect(screen.getByText('secret text')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'הסתרת תוכן' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'הסתרת תוכן' }))
  expect(screen.queryByText('secret text')).not.toBeInTheDocument()
})

test('a fresh view always starts hidden again', async () => {
  const first = render(<Demo />)
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תוכן' }))
  first.unmount()
  render(<Demo />)
  expect(screen.queryByText('secret text')).not.toBeInTheDocument()
})

test('the mask keeps the length in the layout but never the characters', () => {
  const { container } = render(<Masked length={30} />)
  expect(container.textContent).toMatch(/^[• ]+התוכן מוסתר$/)
  expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull()
})

test('the label carries the state, so the button is not also announced as pressed', () => {
  render(<Demo />)
  expect(screen.getByRole('button', { name: 'הצגת תוכן' })).not.toHaveAttribute('aria-pressed')
})

test('a button for one item says which item, for screen readers', () => {
  render(<RevealButton revealed={false} onToggle={() => {}} context="message from Dan" />)
  expect(screen.getByRole('button', { name: 'הצגת תוכן, message from Dan' })).toBeInTheDocument()
})

test('the mask only comes in three sizes, so its length does not give the message away', () => {
  const size = (n: number) => render(<Masked length={n} />).container.textContent!.length
  expect(size(2)).toBe(size(25))
  expect(size(60)).toBe(size(100))
  expect(size(200)).toBe(size(5000))
  expect(size(2)).toBeLessThan(size(60))
})

function Scoped({ id }: { id: string }) {
  const { revealed, toggle } = useReveal(id)
  return (
    <>
      <RevealButton revealed={revealed} onToggle={toggle} />
      <p>{revealed ? `text of ${id}` : 'hidden'}</p>
    </>
  )
}

test('moving to another item hides it again even if the component is reused', async () => {
  const { rerender } = render(<Scoped id="1" />)
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תוכן' }))
  expect(screen.getByText('text of 1')).toBeInTheDocument()
  rerender(<Scoped id="2" />)
  expect(screen.getByText('hidden')).toBeInTheDocument()
})
