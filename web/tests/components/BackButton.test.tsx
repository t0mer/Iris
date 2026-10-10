import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { BackButton } from '../../src/components/BackButton'

test('a direct link returns to a known Iris page when there is no browser history', () => {
  window.history.replaceState({}, '')
  render(
    <MemoryRouter initialEntries={['/direct']}>
      <Routes>
        <Route path="/direct" element={<BackButton fallback="/messages" />} />
        <Route path="/messages" element={<h1>Messages destination</h1>} />
      </Routes>
    </MemoryRouter>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  expect(screen.getByRole('heading', { name: 'Messages destination' })).toBeInTheDocument()
})
