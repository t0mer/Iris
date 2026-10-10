import { fireEvent, render, screen } from '@testing-library/react'
import { OriginalMedia } from '../../src/components/OriginalMedia'

test('does not request media while concealed and shows stickers through Iris when revealed', () => {
  const view = render(<OriginalMedia id={12} type="sticker" revealed={false} />)
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  view.rerender(<OriginalMedia id={12} type="sticker" revealed />)
  expect(screen.getByRole('img', { name: 'Sticker' })).toHaveAttribute(
    'src',
    '/api/media/message/12',
  )
})

test('video uses an authenticated Iris source with playback controls', () => {
  const { container } = render(<OriginalMedia id={13} type="video" revealed />)
  expect(container.querySelector('video')).toHaveAttribute('src', '/api/media/message/13')
  expect(container.querySelector('video')).toHaveAttribute('controls')
})

test('shows the server failure rather than blaming format or size, and allows retry', async () => {
  const detail = 'OpenWA has no saved copy of this media. It was omitted or removed.'
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 404 }))
  render(<OriginalMedia id={112} type="sticker" revealed />)
  fireEvent.error(screen.getByRole('img', { name: 'Sticker' }))
  expect(await screen.findByText(detail)).toBeInTheDocument()
  expect(screen.queryByText(/250 MB/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Retry media' }))
  expect(screen.getByRole('img', { name: 'Sticker' })).toBeInTheDocument()
  fetch.mockRestore()
})

test('a previous media failure does not hide a different message', async () => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 404 }))
  const view = render(<OriginalMedia id={12} type="sticker" revealed />)
  fireEvent.error(screen.getByRole('img'))
  expect(await screen.findByText('Unavailable')).toBeInTheDocument()
  view.rerender(<OriginalMedia id={13} type="image" revealed />)
  expect(screen.getByRole('img')).toHaveAttribute('src', '/api/media/message/13')
  expect(screen.queryByText('Unavailable')).not.toBeInTheDocument()
  fetch.mockRestore()
})
