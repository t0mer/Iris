import { screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Chats } from './Chats'
import { Instances } from './Instances'
import { Jobs } from './Jobs'
import { Review } from './Review'

function renderFailing(ui: React.ReactNode) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 500 })),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

test.each([
  { name: 'Phones', page: () => <Instances />, what: /your phones/ },
  { name: 'Review', page: () => <Review />, what: /the review queue/ },
  { name: 'Jobs', page: () => <Jobs />, what: /the jobs/ },
  { name: 'Chats', page: () => <Chats />, what: /your chats/ },
])(
  '$name says what failed to load and offers to try again, instead of a blank page',
  async ({ page, what }) => {
    renderFailing(page())
    expect(await screen.findByRole('alert')).toHaveTextContent(what)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  },
)
