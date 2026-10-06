import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ActivityChart } from './ActivityChart'

const days = [
  { date: '2026-10-04', safe: 3, review: 0, harmful: 0, other: 0, alerts: 0 },
  { date: '2026-10-05', safe: 0, review: 0, harmful: 0, other: 2, alerts: 0 },
  { date: '2026-10-06', safe: 5, review: 1, harmful: 2, other: 1, alerts: 2 },
]

test('has a text summary, a legend with every series named, and one labelled group per day', () => {
  render(<ActivityChart days={days} />)
  expect(
    screen.getByRole('img', { name: /Busiest day Oct 6 with 8 messages, 2 harmful/ }),
  ).toBeInTheDocument()
  for (const label of ['Fine', 'Worth a look', 'Harmful'])
    expect(screen.getByText(label)).toBeInTheDocument()
  expect(
    screen.getByRole('img', { name: 'Oct 6: 5 fine, 1 worth a look, 2 harmful' }),
  ).toBeInTheDocument()
  expect(screen.getAllByRole('img', { name: /fine, .* harmful$/ })).toHaveLength(3)
})

test('every day can be focused from the keyboard and shows its numbers in a tooltip', () => {
  render(<ActivityChart days={days} />)
  const day = screen.getByRole('img', { name: /^Oct 6:/ })
  expect(day).toHaveAttribute('tabindex', '0')
  fireEvent.focus(day)
  const tip = screen.getByRole('status')
  expect(within(tip).getByText('Alerts sent').nextSibling).toHaveTextContent('2')
  expect(within(tip).getByText('Not checked').nextSibling).toHaveTextContent('1')
  fireEvent.blur(day)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('the same numbers are available as a table, including what the picture leaves out', async () => {
  render(<ActivityChart days={days} />)
  await userEvent.click(screen.getByRole('button', { name: 'Show as table' }))
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(4) // header and three days
  expect(
    within(screen.getByRole('row', { name: /Oct 5/ })).getAllByRole('cell')[3],
  ).toHaveTextContent('2') // not checked
  await userEvent.click(screen.getByRole('button', { name: 'Show chart' }))
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})

test('an empty period still renders without errors', () => {
  const empty = [{ date: '2026-10-06', safe: 0, review: 0, harmful: 0, other: 0, alerts: 0 }]
  render(<ActivityChart days={empty} />)
  expect(screen.getByRole('img', { name: /No messages yet/ })).toBeInTheDocument()
})
