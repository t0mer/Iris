import { useQuery } from '@tanstack/react-query'
import { BellRing, ChevronLeft, FileX, MessagesSquare } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { EmptyState } from '../components/EmptyState'
import { MediaPlayer } from '../components/MediaPlayer'
import { RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { PageHeader } from '../components/PageHeader'
import { QueryError } from '../components/QueryError'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { fileSize } from '../lib/format'
import { strings, t } from '../lib/i18n'
import type { MediaInfo } from '../lib/types'

const LABEL = {
  image: strings.media.photo,
  audio: strings.media.voiceNote,
  video: strings.media.video,
} as const

/** The page the WhatsApp alert links to: the kept file, shown after sign-in. */
export function MediaViewer() {
  const { id } = useParams()
  const { revealed, toggle } = useReveal(id)
  const info = useQuery({
    queryKey: ['media', id],
    queryFn: () => api<MediaInfo>(`/api/media/${id}/info`),
    enabled: /^\d+$/.test(id ?? ''),
    retry: (count, e) => !(e instanceof ApiError && e.status === 404) && count < 2,
  })
  const m = info.data
  const gone =
    !/^\d+$/.test(id ?? '') || (info.error instanceof ApiError && info.error.status === 404)

  if (gone)
    return (
      <div className="flex max-w-3xl flex-col gap-6">
        <PageHeader title={t('mediaViewer.keptMedia')} />
        <EmptyState icon={FileX} title={t('mediaViewer.noLongerKept')}>
          {t('mediaViewer.noLongerKeptBody')}
        </EmptyState>
      </div>
    )
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Link
        to="/alerts"
        className="inline-flex min-h-10 w-fit items-center gap-1 text-sm font-medium text-primary"
      >
        <ChevronLeft className="size-4 rtl:rotate-180" /> {t('mediaViewer.allAlerts')}
      </Link>
      <PageHeader
        title={m ? LABEL[m.kind] : t('mediaViewer.keptMedia')}
        description={m ? `${m.content_type}, ${fileSize(m.size_bytes)}` : undefined}
      />
      {info.isError && (
        <QueryError what={t('mediaViewer.couldNotLoad')} onRetry={() => void info.refetch()} />
      )}
      {!m && !info.isError && <Skeleton className="h-64" />}
      {m && (
        <>
          <div className="flex flex-col items-start gap-3">
            <RevealButton
              revealed={revealed}
              onToggle={toggle}
              label={LABEL[m.kind].toLowerCase()}
            />
            <MediaPlayer media={m} revealed={revealed} />
          </div>
          <div className="flex flex-wrap gap-2">
            {m.alert_id !== null && (
              <Button asChild variant="outline">
                <Link to={`/alerts/${m.alert_id}`}>
                  <BellRing /> {t('mediaViewer.seeAlert')}
                </Link>
              </Button>
            )}
            <Button asChild variant="ghost">
              <Link to={`/messages/${m.message_id}`}>
                <MessagesSquare /> {t('mediaViewer.seeConversation')}
              </Link>
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
