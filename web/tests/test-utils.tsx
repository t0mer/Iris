import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '../src/components/ui/toaster'

export interface Call {
  method: string
  url: string
  body?: unknown
}

/** Stubs fetch with a router of `prefix -> response`, records every call, and renders inside providers. */
export function renderWithApp(ui: ReactNode, routes: Record<string, unknown>, path = '/') {
  routes = {
    '/api/auth/me': { username: 'admin', role: 'admin', id: 1 },
    '/api/messages/groups/skipped/list': [],
    '/api/messages/chats/skipped/list': [],
    ...routes,
  }
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        method: init?.method ?? 'GET',
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      const hit = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((p) => url.startsWith(p))
      return new Response(JSON.stringify(hit ? routes[hit] : {}), { status: 200 })
    }),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        {ui}
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}
