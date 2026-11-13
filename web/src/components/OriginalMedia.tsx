import { t } from '../lib/i18n'
import { useEffect, useRef, useState } from 'react'
import { Button } from './ui/button'
import { DocumentViewer } from './DocumentViewer'
import { Link } from 'react-router-dom'

/** Only Iris serves the bytes; OpenWA credentials never reach the browser. */
export function OriginalMedia({
  id,
  type,
  revealed,
  standalone = false,
}: {
  id: number
  type: string
  revealed: boolean
  standalone?: boolean
}) {
  const [failed, setFailed] = useState('')
  const pending = useRef<AbortController | null>(null)
  useEffect(() => {
    pending.current?.abort()
    setFailed('')
    return () => pending.current?.abort()
  }, [id, revealed])
  async function explainFailure() {
    setFailed('Checking why the original media could not load…')
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    try {
      const response = await fetch(`/api/media/message/${id}`, {
        signal: controller.signal,
        credentials: 'same-origin',
      })
      if (response.ok) {
        await response.body?.cancel()
        if (!controller.signal.aborted)
          setFailed(
            'The media is available, but this browser could not display it. Try opening the original below.',
          )
      } else {
        const data = await response.json()
        if (!controller.signal.aborted)
          setFailed(
            typeof data.detail === 'string'
              ? data.detail
              : 'Could not retrieve the original media. Try again.',
          )
      }
    } catch {
      if (!controller.signal.aborted)
        setFailed('Could not reach Iris to retrieve this media. Try again.')
    }
  }
  if (!revealed)
    return (
      <span className="text-sm text-muted-foreground">
        {t('Media hidden — use Show content to view.')}
      </span>
    )
  if (type === 'document') return <DocumentViewer key={id} id={id} />
  if (failed)
    return (
      <div className="flex flex-col gap-2 text-sm">
        <p role="alert">{t(failed)}</p>
        {type === 'sticker' && failed.includes('no saved copy') && (
          <p>
            {t(
              'This sticker is unavailable in OpenWA. Iris cannot display it without the original file.',
            )}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              pending.current?.abort()
              setFailed('')
            }}
          >
            {t('Retry media')}
          </Button>
          <Button asChild variant="ghost" size="sm">
            {standalone ? (
              <a href={`/api/media/message/${id}`} download>
                {t('Download original')}
              </a>
            ) : (
              <Link to={`/messages/${id}/original`}>{t('Open original')}</Link>
            )}
          </Button>
        </div>
      </div>
    )
  const props = { src: `/api/media/message/${id}`, onError: () => void explainFailure() }
  if (type === 'video')
    return <video {...props} controls preload="metadata" className="max-h-80 max-w-full" />
  if (type === 'voice' || type === 'audio')
    return <audio {...props} controls preload="metadata" className="w-full max-w-full min-w-0" />
  return (
    <img
      {...props}
      alt={t(type === 'sticker' ? 'Sticker' : 'Message image')}
      className="max-h-64 max-w-full object-contain"
    />
  )
}
