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
    screen.getByRole('group', { name: /היום העמוס ביותר: 6 באוק׳, 8 הודעות, מתוכן 2 מזיקות/ }),
  ).toBeInTheDocument()
  for (const label of ['תקין', 'כדאי לבדוק', 'מזיק'])
    expect(screen.getByText(label)).toBeInTheDocument()
  expect(
    screen.getByRole('img', { name: '6 באוק׳: 5 תקינות, 1 כדאי לבדוק, 2 מזיקות' }),
  ).toBeInTheDocument()
  expect(screen.getAllByRole('img', { name: /תקינות, .* מזיקות$/ })).toHaveLength(3)
})

test('every day can be focused from the keyboard and shows its numbers in a tooltip', () => {
  render(<ActivityChart days={days} />)
  const day = screen.getByRole('img', { name: /^6 באוק׳:/ })
  expect(day).toHaveAttribute('tabindex', '0')
  fireEvent.focus(day)
  const tip = screen.getByText('התראות שנשלחו').closest('div')!
  expect(tip).toHaveAttribute('aria-hidden', 'true') // visual only: the labels and the table carry the data
  expect(within(tip).getByText('התראות שנשלחו').nextSibling).toHaveTextContent('2')
  expect(within(tip).getByText('לא נבדק').nextSibling).toHaveTextContent('1')
  fireEvent.blur(day)
  expect(screen.queryByText('התראות שנשלחו')).not.toBeInTheDocument()
})

test('the same numbers are available as a table, including what the picture leaves out', async () => {
  render(<ActivityChart days={days} />)
  await userEvent.click(screen.getByRole('button', { name: 'הצגה כטבלה' }))
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(4) // header and three days
  expect(
    within(screen.getByRole('row', { name: /5 באוק׳/ })).getAllByRole('cell')[3],
  ).toHaveTextContent('2') // not checked
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תרשים' }))
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})

test('an empty period still renders without errors', () => {
  const empty = [{ date: '2026-10-06', safe: 0, review: 0, harmful: 0, other: 0, alerts: 0 }]
  render(<ActivityChart days={empty} />)
  expect(screen.getByRole('group', { name: /אין עדיין הודעות/ })).toBeInTheDocument()
})

test('keeps observing whichever element holds the chart after switching to the table and back', async () => {
  const observed: Element[] = []
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(el: Element) {
        observed.push(el)
      }
      unobserve() {}
      disconnect() {}
    },
  )
  const { container } = render(<ActivityChart days={days} />)
  await userEvent.click(screen.getByRole('button', { name: 'הצגה כטבלה' }))
  await userEvent.click(screen.getByRole('button', { name: 'הצגת תרשים' }))
  const holder = container.querySelector('svg')!.parentElement!
  expect(observed.at(-1)).toBe(holder) // the live chart container is the one being observed
})
