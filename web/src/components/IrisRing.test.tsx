import { render, screen } from '@testing-library/react'
import { IrisRing } from './IrisRing'

const arcs = (container: HTMLElement) => [...container.querySelectorAll('circle.iris-arc')]
const length = (c: Element) => Number(c.getAttribute('stroke-dasharray')!.split(' ')[0])

test('calm is a single full violet ring that says nothing needs attention', () => {
  const { container } = render(<IrisRing alerts={0} review={0} />)
  expect(screen.getByRole('img', { name: 'Nothing needs your attention' })).toBeInTheDocument()
  const [only, ...rest] = arcs(container)
  expect(rest).toHaveLength(0)
  expect(only.getAttribute('stroke')).toBe('var(--primary)')
})

test('alerts and review items become coral and saffron arcs sized by their counts', () => {
  const { container } = render(<IrisRing alerts={3} review={1} />)
  expect(screen.getByRole('img', { name: '4 need your attention' })).toBeInTheDocument()
  const [alerts, review] = arcs(container)
  expect(alerts.getAttribute('stroke')).toBe('var(--danger)')
  expect(review.getAttribute('stroke')).toBe('var(--chart-review)')
  // three alerts versus one review item: roughly three times as long (round caps trim both by the same amount)
  expect(length(alerts)).toBeGreaterThan(length(review) * 2.5)
})

test('with only one kind of item the whole ring is that colour', () => {
  const { container } = render(<IrisRing alerts={0} review={2} />)
  const found = arcs(container)
  expect(found).toHaveLength(1)
  expect(found[0].getAttribute('stroke')).toBe('var(--chart-review)')
})
