import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { renderWithApp } from '../test-utils'
import { MediaViewer } from '../../src/pages/MediaViewer'

const info = {
  id: 9,
  kind: 'image',
  content_type: 'image/png',
  size_bytes: 1_500_000,
  inline: true,
  message_id: 4,
  alert_id: 3,
}

function page(routes: Record<string, unknown>) {
  return renderWithApp(
    <Routes>
      <Route path="/media/:id" element={<MediaViewer />} />
    </Routes>,
    routes,
    '/media/9',
  )
}

test('shows the file with links to its alert and conversation', async () => {
  page({ '/api/media/9/info': info })
  expect(await screen.findByText('Photo hidden')).toBeInTheDocument() // hidden until shown
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show photo' }))
  expect(await screen.findByRole('img', { name: /photo kept/ })).toHaveAttribute(
    'src',
    '/api/media/9',
  )
  expect(screen.getByRole('heading', { name: 'Photo' })).toBeInTheDocument()
  expect(screen.getByText('image/png, 1.4 MB')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /See the alert/ })).toHaveAttribute('href', '/alerts/3')
  expect(screen.getByRole('link', { name: /See the conversation/ })).toHaveAttribute(
    'href',
    '/messages/4',
  )
})

test('omits the alert link when the media has no alert', async () => {
  page({ '/api/media/9/info': { ...info, alert_id: null } })
  await screen.findByText('Photo hidden')
  expect(screen.queryByRole('link', { name: /See the alert/ })).not.toBeInTheDocument()
})

test('a file that is gone says so instead of failing', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'Media not found' }), { status: 404 })),
  )
  const { render } = await import('@testing-library/react')
  const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
  const { MemoryRouter } = await import('react-router-dom')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/media/9']}>
        <Routes>
          <Route path="/media/:id" element={<MediaViewer />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('This file is no longer kept')).toBeInTheDocument()
})

test('an address that is not a number is simply "no longer kept"', async () => {
  const calls = renderWithApp(
    <Routes>
      <Route path="/media/:id" element={<MediaViewer />} />
    </Routes>,
    {},
    '/media/abc',
  )
  expect(await screen.findByText('This file is no longer kept')).toBeInTheDocument()
  expect(calls.length).toBe(0)
})

test('a video is called a video, not a voice note', async () => {
  page({ '/api/media/9/info': { ...info, kind: 'video', content_type: 'video/mp4' } })
  expect(await screen.findByRole('button', { name: 'Show video' })).toBeInTheDocument()
  expect(screen.getByText('Video hidden')).toBeInTheDocument()
})
