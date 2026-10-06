import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Pagination } from './Pagination'

const noun: [string, string] = ['message', 'messages']

test('says how many there are, with the right singular or plural, when one page is enough', () => {
  const { rerender } = render(
    <Pagination page={1} pageSize={25} total={1} noun={noun} onPage={() => {}} />,
  )
  expect(screen.getByText('1 message')).toBeInTheDocument()
  rerender(<Pagination page={1} pageSize={25} total={7} noun={noun} onPage={() => {}} />)
  expect(screen.getByText('7 messages')).toBeInTheDocument()
  rerender(<Pagination page={1} pageSize={25} total={0} noun={noun} onPage={() => {}} />)
  expect(screen.queryByText(/messages?$/)).not.toBeInTheDocument()
})

test('pages forward and back and disables the ends', async () => {
  const onPage = vi.fn()
  const { rerender } = render(
    <Pagination page={1} pageSize={25} total={60} noun={noun} onPage={onPage} />,
  )
  expect(screen.getByText('1 to 25 of 60 messages')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Previous/ })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: /Next/ }))
  expect(onPage).toHaveBeenCalledWith(2)
  rerender(<Pagination page={3} pageSize={25} total={60} noun={noun} onPage={onPage} />)
  expect(screen.getByText('51 to 60 of 60 messages')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Next/ })).toBeDisabled()
})

test('a page past the end explains itself and still offers a way back', async () => {
  const onPage = vi.fn()
  render(
    <Pagination page={4} pageSize={25} total={12} noun={['message', 'messages']} onPage={onPage} />,
  )
  expect(screen.getByText(/Nothing on page 4/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Previous/ }))
  expect(onPage).toHaveBeenCalledWith(3)
})
