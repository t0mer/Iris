import { render, screen } from '@testing-library/react'
import { Highlight } from '../../src/components/Highlight'

test('wraps only marked text and never renders HTML', () => {
  render(<Highlight snippet={'a \x02שלום\x03 <b>x</b>'} revealed />)
  expect(screen.getByText('שלום').tagName).toBe('MARK')
  expect(screen.getByText(/<b>x<\/b>/)).toBeInTheDocument()
})

test('hidden, it shows none of the real characters', () => {
  const { container } = render(<Highlight snippet={'a \x02secret\x03 words'} />)
  expect(container).not.toHaveTextContent('secret')
  expect(screen.getByText('Content hidden')).toBeInTheDocument()
})
