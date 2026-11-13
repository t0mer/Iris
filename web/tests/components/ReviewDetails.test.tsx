import { render, screen, fireEvent } from '@testing-library/react'
import { ReviewDetails, reviewCategories } from '../../src/components/ReviewDetails'
import { setLanguage } from '../../src/lib/i18n'
afterEach(() => setLanguage('system'))
test('Hebrew review categories display translated names but retain canonical values', () => {
  setLanguage('he')
  const change = vi.fn()
  const { container } = render(
    <ReviewDetails
      id={1}
      value={{ categories: [], explanation: '' }}
      onChange={change}
      disabled={false}
    />,
  )
  const details = container.querySelector('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  expect(screen.getAllByRole('checkbox')).toHaveLength(reviewCategories.length)
  fireEvent.click(screen.getByLabelText('כוונה לפגיעה עצמית'))
  expect(change).toHaveBeenCalledWith({ categories: ['self-harm/intent'], explanation: '' })
  expect(screen.queryByText('sexual / minors')).not.toBeInTheDocument()
})
