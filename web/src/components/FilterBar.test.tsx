import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Chips, FilterBar } from './FilterBar'

function viewport(desktop: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((q: string) => ({
      matches: q.includes('min-width') ? desktop : false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  )
}

const controls = (
  <label>
    Phone
    <select>
      <option>All</option>
    </select>
  </label>
)

test('on desktop the filters are inline and clearing is offered only when something is active', async () => {
  viewport(true)
  const onClear = vi.fn()
  const { rerender } = render(
    <FilterBar active={0} onClear={onClear}>
      {controls}
    </FilterBar>,
  )
  expect(screen.getByLabelText('Phone')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument()
  rerender(
    <FilterBar active={2} onClear={onClear}>
      {controls}
    </FilterBar>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect(onClear).toHaveBeenCalled()
})

test('on a phone the filters hide behind one button that shows how many are active', async () => {
  viewport(false)
  render(
    <FilterBar active={2} onClear={() => {}} leading={<span>search box</span>}>
      {controls}
    </FilterBar>,
  )
  expect(screen.getByText('search box')).toBeInTheDocument() // always visible
  expect(screen.queryByLabelText('Phone')).not.toBeInTheDocument()
  const open = screen.getByRole('button', { name: /Filters/ })
  expect(open).toHaveTextContent('2')
  await userEvent.click(open)
  expect(await screen.findByRole('dialog', { name: 'Filters' })).toBeInTheDocument()
  expect(screen.getByLabelText('Phone')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show results' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('chips are single choice, announce which is pressed and report the choice', async () => {
  const onChange = vi.fn()
  render(
    <Chips
      label="Status"
      value=""
      options={[
        { value: '', label: 'All' },
        { value: 'new', label: 'New' },
      ]}
      onChange={onChange}
    />,
  )
  expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'New' }))
  expect(onChange).toHaveBeenCalledWith('new')
})
