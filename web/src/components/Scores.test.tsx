import { render, screen } from '@testing-library/react'
import { CategoryChips, Scores } from './Scores'

test('shows scores sorted high to low, hides tiny ones and the _meta entry', () => {
  render(
    <Scores
      scores={{ hate: 0.01, violence: 0.94, harassment: 0.3, _meta: { api_flagged: true } }}
    />,
  )
  const items = screen.getAllByRole('listitem').map((li) => li.textContent)
  expect(items).toEqual(['violence0.94', 'harassment0.30'])
})

test('chips show the top score only on the first category', () => {
  const { container } = render(
    <CategoryChips categories={['violence', 'harassment']} score={0.944} />,
  )
  expect(container).toHaveTextContent('violence 0.94')
  expect(container).toHaveTextContent('harassment')
  expect(container).not.toHaveTextContent('harassment 0.')
})
