import { render, screen } from '@testing-library/react'
import { PageBoundary } from '../../src/components/PageBoundary'

test('a failed page presents recovery instead of breaking navigation', () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {})
  function Broken(): never {
    throw new Error('Failed to fetch dynamically imported module')
  }
  const view = render(
    <PageBoundary key="old">
      <Broken />
    </PageBoundary>,
  )
  expect(screen.getByRole('alert')).toHaveTextContent('This page could not load')
  expect(screen.getByRole('button', { name: 'Reload Iris' })).toBeInTheDocument()
  view.rerender(
    <PageBoundary key="new">
      <h1>Another page</h1>
    </PageBoundary>,
  )
  expect(screen.getByRole('heading', { name: 'Another page' })).toBeInTheDocument()
  log.mockRestore()
})
