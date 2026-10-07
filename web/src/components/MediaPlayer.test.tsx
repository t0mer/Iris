import { fireEvent, render, screen } from '@testing-library/react'
import type { KeptMedia } from '../lib/types'
import { MediaBadge, MediaPlayer } from './MediaPlayer'

const base: KeptMedia = {
  id: 5,
  kind: 'image',
  content_type: 'image/png',
  size_bytes: 2048,
  inline: true,
}

test('an image is shown from Iris itself, never from the storage', () => {
  render(<MediaPlayer media={base} />)
  const img = screen.getByRole('img', { name: /photo kept/ })
  expect(img).toHaveAttribute('src', '/api/media/5')
})

test('a voice note gets audio controls and a video gets video controls', () => {
  const { container, rerender } = render(
    <MediaPlayer media={{ ...base, kind: 'audio', content_type: 'audio/ogg' }} />,
  )
  expect(container.querySelector('audio')).toHaveAttribute('src', '/api/media/5')
  expect(container.querySelector('audio')).toHaveAttribute('controls')
  rerender(<MediaPlayer media={{ ...base, kind: 'video', content_type: 'video/mp4' }} />)
  expect(container.querySelector('video')).toHaveAttribute('src', '/api/media/5')
})

test('a type browsers cannot play is offered as a download', () => {
  render(
    <MediaPlayer media={{ ...base, kind: 'audio', content_type: 'audio/amr', inline: false }} />,
  )
  const link = screen.getByRole('link', { name: /Download the voice note \(2 KB\)/ })
  expect(link).toHaveAttribute('href', '/api/media/5')
  expect(link).toHaveAttribute('download')
})

test('the badge names the kind and the size', () => {
  render(<MediaBadge media={{ ...base, kind: 'video', size_bytes: 5 * 1024 * 1024 }} />)
  expect(screen.getByText('Video kept')).toHaveAttribute('title', 'Video kept, 5.0 MB')
})

test('a file that cannot be loaded says so instead of showing a broken picture', () => {
  render(<MediaPlayer media={base} />)
  fireEvent.error(screen.getByRole('img', { name: /photo kept/ }))
  expect(screen.getByRole('alert')).toHaveTextContent('could not be loaded')
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})
