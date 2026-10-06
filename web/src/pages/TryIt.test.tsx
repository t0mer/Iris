import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { TryIt } from './TryIt'
import { NAV } from '../components/nav'

const rows = [
  ['violence', 0.2, 0.7],
  ['harassment', 0.2, 0.7],
].map(([category, low, high]) => ({
  category,
  low,
  high,
  default_low: low,
  default_high: high,
}))
const response = {
  model: 'omni-moderation-latest',
  verdict: 'review',
  thresholds: rows,
  stages: [{ stage: 'moderation', scores: { violence: 0.4, harassment: 0.01 } }],
}

async function check(routes: Record<string, unknown> = { '/api/classify/test': response }) {
  const calls = renderWithApp(<TryIt />, routes)
  await userEvent.type(screen.getByLabelText('Message to check'), 'hello there')
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  await screen.findByText('Thresholds')
  return calls
}

test('the check button needs text', () => {
  renderWithApp(<TryIt />, {})
  expect(screen.getByRole('button', { name: /Check/ })).toBeDisabled()
})

test('sends the text and the context lines, one per line', async () => {
  const calls = renderWithApp(<TryIt />, { '/api/classify/test': response })
  await userEvent.type(screen.getByLabelText('Message to check'), 'final')
  await userEvent.type(screen.getByLabelText(/Earlier messages/), 'one{enter}{enter}two')
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  await screen.findByText('Thresholds')
  const post = calls.find((c) => c.url === '/api/classify/test')
  expect(post!.body).toEqual({ text: 'final', context: ['one', 'two'] })
})

test('shows the verdict from the saved thresholds', async () => {
  await check()
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
})

test('editing a threshold changes the verdict without another request', async () => {
  const calls = await check()
  const before = calls.filter((c) => c.url === '/api/classify/test').length
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  expect(screen.getByRole('heading', { name: 'Harmful' })).toBeInTheDocument()
  expect(calls.filter((c) => c.url === '/api/classify/test')).toHaveLength(before)
})

test('save sends only the rows that differ from the defaults', async () => {
  const calls = await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  await userEvent.click(screen.getByRole('button', { name: /Save these thresholds/ }))
  const put = calls.find((c) => c.method === 'PUT')
  expect(put!.body).toEqual({
    settings: { 'classification.thresholds': { violence: { low: 0.2, high: 0.35 } } },
  })
})

test('an invalid range cannot be saved and says why', async () => {
  const calls = await check()
  const low = screen.getByLabelText('violence needs a look')
  await userEvent.clear(low)
  await userEvent.type(low, '0.9')
  expect(screen.getByRole('button', { name: /Save these thresholds/ })).toBeDisabled()
  expect(screen.getByText(/Fix the highlighted values/)).toBeInTheDocument()
  expect(calls.some((c) => c.method === 'PUT')).toBe(false)
})

test('a half-typed value does not change the verdict', async () => {
  await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high) // blank
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
  await userEvent.type(high, '-')
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
})

test('threshold edits survive checking another phrase', async () => {
  await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  expect(await screen.findByRole('heading', { name: 'Harmful' })).toBeInTheDocument()
  expect(screen.getByLabelText('violence harmful')).toHaveValue(0.35)
})

test('too many context lines are refused before sending', async () => {
  const calls = renderWithApp(<TryIt />, { '/api/classify/test': response })
  await userEvent.type(screen.getByLabelText('Message to check'), 'x')
  await userEvent.type(
    screen.getByLabelText(/Earlier messages/),
    Array.from({ length: 21 }, (_, i) => `l${i}`).join('{enter}'),
  )
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  expect(await screen.findByText(/at most 20 earlier messages/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/classify/test')).toBe(false)
})

test('reset returns to the saved values', async () => {
  await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  await userEvent.click(screen.getByRole('button', { name: /Reset to saved/ }))
  expect(screen.getByLabelText('violence harmful')).toHaveValue(0.7)
})

test('the page is in the navigation', () => {
  expect(NAV.some((n) => n.to === '/try' && n.label === 'Try it')).toBe(true)
})
