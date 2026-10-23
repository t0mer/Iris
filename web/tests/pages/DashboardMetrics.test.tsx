import { render, screen } from '@testing-library/react'
import { setLanguage } from '../../src/lib/i18n'
import { DashboardMetrics } from '../../src/components/DashboardMetrics'

afterEach(() => setLanguage('system'))

test('renders three distinct accessible metrics in Hebrew and RTL', () => {
  setLanguage('he')
  const { container } = render(
    <DashboardMetrics
      disk={{ percentage: 68, usedBytes: 136e9, totalBytes: 200e9, freeBytes: 64e9 }}
      memory={{ percentage: 50, usedBytes: 8e9, totalBytes: 16e9 }}
      cpu={{ percentage: 85, cores: 4 }}
    />,
  )
  expect(container.firstChild).toHaveAttribute('dir', 'rtl')
  expect(screen.getByRole('heading', { name: 'דיסק' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'מעבד' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'זיכרון' })).toBeInTheDocument()
  expect(screen.getAllByRole('meter')).toHaveLength(3)
  expect(screen.getByRole('meter', { name: /מעבד/ })).toHaveAttribute('aria-valuenow', '85')
  expect(screen.getByText(/136 GB/)).toBeInTheDocument()
  expect(screen.getByText(/8 GB/)).toBeInTheDocument()
})
test('shows unavailable readings without false zero percentages', () => {
  render(
    <DashboardMetrics
      disk={{ percentage: null, usedBytes: null, totalBytes: null }}
      memory={{ percentage: null, usedBytes: null, totalBytes: null }}
      cpu={{ percentage: null, cores: null }}
    />,
  )
  expect(screen.queryByRole('meter')).not.toBeInTheDocument()
  expect(screen.getAllByRole('img')).toHaveLength(3)
  expect(screen.queryByText('0%')).not.toBeInTheDocument()
})
