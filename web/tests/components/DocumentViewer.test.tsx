import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { OriginalMedia } from '../../src/components/OriginalMedia'
import { DocumentViewer } from '../../src/components/DocumentViewer'
vi.mock('../../src/components/PdfDocument', () => ({
  PdfDocument: ({ data }: { data: ArrayBuffer }) => <div>PDF bytes: {data.byteLength}</div>,
}))

test('document is not fetched until content is revealed', async () => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response('%PDF-1.7', { headers: { 'content-type': 'application/pdf' } }))
  const view = render(<OriginalMedia id={911} type="document" revealed={false} />, {
    wrapper: MemoryRouter,
  })
  expect(fetch).not.toHaveBeenCalled()
  view.rerender(<OriginalMedia id={911} type="document" revealed />)
  expect(await screen.findByText('PDF bytes: 8')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith(
    '/api/media/message/911',
    expect.objectContaining({ credentials: 'same-origin' }),
  )
  expect(screen.getByRole('link', { name: 'Download document' })).toHaveAttribute('download')
})
test('other document formats offer download without executing or previewing their content', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response('<html>untrusted</html>', {
      headers: { 'content-type': 'application/octet-stream' },
    }),
  )
  render(<DocumentViewer id={912} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('cannot be previewed')
  expect(screen.queryByText(/PDF bytes/)).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Download document' })).toHaveAttribute(
    'href',
    '/api/media/message/912',
  )
})
test('missing document shows the original failure instead of a blank preview', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ detail: 'OpenWA has no saved copy of this media.' }), {
      status: 404,
    }),
  )
  render(<DocumentViewer id={913} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('OpenWA has no saved copy')
})
