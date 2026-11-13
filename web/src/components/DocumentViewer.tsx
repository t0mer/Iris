import { lazy, Suspense, useEffect, useState } from 'react'
import { Button } from './ui/button'
import { t } from '../lib/i18n'
const PdfDocument = lazy(() => import('./PdfDocument').then((m) => ({ default: m.PdfDocument })))

export function DocumentViewer({ id }: { id: number }) {
  const [data, setData] = useState<ArrayBuffer | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const src = `/api/media/message/${id}`
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const response = await fetch(src, { credentials: 'same-origin', signal: controller.signal })
        if (!response.ok) {
          const detail = await response.json()
          throw new Error(
            typeof detail.detail === 'string' ? detail.detail : 'Could not load document.',
          )
        }
        if (!response.headers.get('content-type')?.startsWith('application/pdf')) {
          await response.body?.cancel()
          setError('This document format can be downloaded, but cannot be previewed in Iris.')
          return
        }
        if (Number(response.headers.get('content-length')) > 50 * 1024 * 1024) {
          await response.body?.cancel()
          throw new Error('This PDF is too large to preview. Download it to view.')
        }
        const bytes = await response.arrayBuffer()
        if (!controller.signal.aborted) setData(bytes)
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : 'Could not load document.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [src])
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {loading && <p role="status">{t('Loading document…')}</p>}
      {error && <p role="alert">{t(error)}</p>}
      {data && (
        <Suspense fallback={<p role="status">{t('Loading document…')}</p>}>
          <PdfDocument data={data} />
        </Suspense>
      )}
      <Button asChild variant="outline">
        <a href={src} download>
          {t('Download document')}
        </a>
      </Button>
    </div>
  )
}
