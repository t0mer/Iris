import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { Button } from './ui/button'
import { t } from '../lib/i18n'
GlobalWorkerOptions.workerSrc = workerUrl

export function PdfDocument({ data }: { data: ArrayBuffer }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [error, setError] = useState('')
  const [width, setWidth] = useState(0)
  const canvas = useRef<HTMLCanvasElement>(null)
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!container.current) return
    const observer = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width))
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let active = true
    const task = getDocument({
      data: new Uint8Array(data.slice(0)),
      useSystemFonts: true,
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
      wasmUrl: '/pdfjs/wasm/',
    })
    task.promise
      .then((pdf) => {
        if (active) setDocument(pdf)
      })
      .catch(() => {
        if (active)
          setError(
            'Could not preview this PDF. It may be damaged or password protected. Download it to view.',
          )
      })
    return () => {
      active = false
      void task.destroy()
    }
  }, [data])
  useEffect(() => {
    if (!document || !canvas.current) return
    let active = true
    let cancel: (() => void) | undefined
    document
      .getPage(page)
      .then((pdfPage) => {
        if (!active || !canvas.current) return
        const base = pdfPage.getViewport({ scale: 1 })
        const availableWidth = Math.max(100, width || container.current?.clientWidth || 600)
        const viewport = pdfPage.getViewport({
          scale: Math.min(availableWidth / base.width, 2) * zoom,
        })
        const target = canvas.current
        const dpr = Math.min(window.devicePixelRatio || 1, 2)
        target.width = Math.ceil(viewport.width * dpr)
        target.height = Math.ceil(viewport.height * dpr)
        target.style.width = `${viewport.width}px`
        target.style.height = `${viewport.height}px`
        const render = pdfPage.render({
          canvas: target,
          viewport,
          transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
        })
        cancel = () => render.cancel()
        return render.promise
      })
      .catch((e) => {
        if (active && e?.name !== 'RenderingCancelledException')
          setError(
            'Could not preview this PDF. It may be damaged or password protected. Download it to view.',
          )
      })
    return () => {
      active = false
      cancel?.()
    }
  }, [document, page, zoom, width])
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {error && <p role="alert">{t(error)}</p>}
      {!document && !error && <p role="status">{t('Loading document…')}</p>}
      {document && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            {t('Previous')}
          </Button>
          <span aria-live="polite">
            {t('Page {value0} of {value1}', { value0: page, value1: document.numPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= document.numPages}
            onClick={() => setPage(page + 1)}
          >
            {t('Next')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={zoom <= 1}
            onClick={() => setZoom(Math.max(1, zoom - 0.25))}
          >
            {t('Zoom out')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={zoom >= 2}
            onClick={() => setZoom(Math.min(2, zoom + 0.25))}
          >
            {t('Zoom in')}
          </Button>
        </div>
      )}
      <div
        ref={container}
        className="max-h-[75vh] min-w-0 max-w-full overflow-auto rounded-md border bg-white"
        dir="ltr"
      >
        <canvas
          ref={canvas}
          role="img"
          aria-label={t('PDF page {value0}', { value0: page })}
          className="block"
        />
      </div>
    </div>
  )
}
