import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
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
  const nav = await screen.findByRole('navigation', { name: 'ניווט ראשי' })
  for (const name of ['בית', 'התראות', 'בדיקה', 'הודעות', 'צ׳אטים', 'טלפונים', 'משימות', 'הגדרות'])
    expect(within(nav).getByRole('link', { name: new RegExp(name) })).toBeInTheDocument()
  expect(await within(nav).findByText('3 ממתינות')).toBeInTheDocument() // new alerts
  expect(within(nav).getByText('2 ממתינות')).toBeInTheDocument() // review queue
  expect(within(nav).getByRole('link', { name: /התראות/ })).toHaveAttribute('aria-current', 'page')
})

test('phone shows a tab bar with four destinations and More for the rest', async () => {
  setViewport(false)
  renderLayout('/')
  const nav = await screen.findByRole('navigation', { name: 'ניווט ראשי' })
  expect(within(nav).getAllByRole('link')).toHaveLength(4)
  expect(within(nav).queryByRole('link', { name: 'הגדרות' })).not.toBeInTheDocument()
  await userEvent.click(within(nav).getByRole('button', { name: /עוד/ }))
  const more = await screen.findByRole('navigation', { name: 'עוד' })
  for (const name of ['צ׳אטים', 'טלפונים', 'משימות', 'הגדרות'])
    expect(within(more).getByRole('link', { name: new RegExp(name) })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /התנתקות/ })).toBeInTheDocument()
})

test('the page can be reached with the skip link and has a main landmark', async () => {
  setViewport(true)
  renderLayout()
  expect(await screen.findByRole('link', { name: 'מעבר לתוכן' })).toHaveAttribute('href', '#main')
  expect(screen.getByRole('main')).toHaveTextContent('page body')
})

test('moves focus to the page after navigating, but not on the first load', async () => {
  setViewport(true)
  renderLayout('/alerts')
  const main = await screen.findByRole('main')
  expect(main).not.toHaveFocus() // the first load leaves focus where the browser put it
  await userEvent.click(
    within(await screen.findByRole('navigation', { name: 'ניווט ראשי' })).getByRole('link', {
      name: /הודעות/,
    }),
  )
  expect(main).toHaveFocus()
})

test('a live alert shows a toast and counts in the tab title until the tab is seen again', async () => {
  setViewport(true)
  const sources: { listeners: Record<string, ((e: { data: string }) => void)[]> }[] = []
  vi.stubGlobal(
    'EventSource',
    class {
      listeners: Record<string, ((e: { data: string }) => void)[]> = {}
      constructor() {
        sources.push(this)
      }
      addEventListener(n: string, f: (e: { data: string }) => void) {
        ;(this.listeners[n] ??= []).push(f)
      }
      close() {}
    },
  )
  document.title = 'Iris'
  renderLayout()
  await screen.findByRole('navigation', { name: 'ניווט ראשי' })
  const s = sources[sources.length - 1]!
  act(() => s.listeners.hello![0]!({ data: '{}' }))
  expect(await screen.findByText('בזמן אמת')).toBeInTheDocument()
  act(() => s.listeners.alert![0]!({ data: '{"id": 5}' }))
  expect(await screen.findByText('יש התראה חדשה')).toBeInTheDocument() // visible tab: toast, no count
  expect(document.title).toBe('Iris') // looking at the tab: no count
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  act(() => s.listeners.alert![0]!({ data: '{"id": 5}' }))
  expect(await screen.findByText('יש התראה חדשה')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'פתיחה' })).toHaveLength(2)
  expect(document.title).toBe('(1) Iris')
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
  expect(document.title).toBe('Iris')
})
