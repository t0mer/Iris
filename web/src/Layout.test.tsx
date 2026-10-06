import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './Layout'

const stats = {
  messages_today: 0,
  messages_7d: 0,
  alerts_by_status: { new: 3 },
  alerts_by_delivery: {},
  review_queue: 2,
  jobs_by_status: {},
  queue_depth: 0,
  failed_jobs: 1,
  delivery_configured: true,
  instances: 1,
  silent_instances: 0,
}

function setViewport(desktop: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((q: string) => ({
      matches: q.includes('min-width: 768')
        ? desktop
        : q.includes('min-width: 1024')
          ? desktop
          : false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  )
}

function renderLayout(path = '/alerts') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const body = url.startsWith('/api/stats')
        ? stats
        : url.startsWith('/api/auth/me')
          ? { username: 'admin' }
          : { version: '2026.10.0' }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="*" element={<p>page body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('desktop shows the sidebar with every destination and live badges', async () => {
  setViewport(true)
  renderLayout()
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  for (const name of [
    'Home',
    'Alerts',
    'Review',
    'Messages',
    'Chats',
    'Phones',
    'Jobs',
    'Settings',
  ])
    expect(within(nav).getByRole('link', { name: new RegExp(name) })).toBeInTheDocument()
  expect(await within(nav).findByText('3 waiting')).toBeInTheDocument() // new alerts
  expect(within(nav).getByText('2 waiting')).toBeInTheDocument() // review queue
  expect(within(nav).getByRole('link', { name: /Alerts/ })).toHaveAttribute('aria-current', 'page')
})

test('phone shows a tab bar with four destinations and More for the rest', async () => {
  setViewport(false)
  renderLayout('/')
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  expect(within(nav).getAllByRole('link')).toHaveLength(4)
  expect(within(nav).queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()
  await userEvent.click(within(nav).getByRole('button', { name: /More/ }))
  const more = await screen.findByRole('navigation', { name: 'More' })
  for (const name of ['Chats', 'Phones', 'Jobs', 'Settings'])
    expect(within(more).getByRole('link', { name: new RegExp(name) })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Sign out/ })).toBeInTheDocument()
})

test('the page can be reached with the skip link and has a main landmark', async () => {
  setViewport(true)
  renderLayout()
  expect(await screen.findByRole('link', { name: 'Skip to content' })).toHaveAttribute(
    'href',
    '#main',
  )
  expect(screen.getByRole('main')).toHaveTextContent('page body')
})

test('moves focus to the page after navigating, but not on the first load', async () => {
  setViewport(true)
  renderLayout('/alerts')
  const main = await screen.findByRole('main')
  expect(main).not.toHaveFocus() // the first load leaves focus where the browser put it
  await userEvent.click(
    within(await screen.findByRole('navigation', { name: 'Main' })).getByRole('link', {
      name: /Messages/,
    }),
  )
  expect(main).toHaveFocus()
})
