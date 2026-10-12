import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { BackButton } from '../components/BackButton'
import { OriginalMedia } from '../components/OriginalMedia'
import { PageHeader } from '../components/PageHeader'
import { PageLoading } from '../components/PageLoading'
import { QueryError } from '../components/QueryError'
import { RevealButton } from '../components/Reveal'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import type { MessageDetail } from '../lib/types'
import { useReveal } from '../lib/useReveal'

export function OriginalMediaViewer() {
  const { id } = useParams()
  const { revealed, toggle } = useReveal(id)
  const query = useQuery({
    queryKey: ['message', id],
    queryFn: () => api<MessageDetail>(`/api/messages/${id}`),
    enabled: /^\d+$/.test(id ?? ''),
  })
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <BackButton fallback={/^\d+$/.test(id ?? '') ? `/messages/${id}` : '/messages'} />
      <PageHeader
        title={t('Original media')}
        description={t(
          'Media from OpenWA is shown inside Iris. Use Back to return to your conversation.',
        )}
      />
      {query.isLoading && <PageLoading />}
      {query.isError && <QueryError what="the media" onRetry={() => void query.refetch()} />}
      {query.data && (
        <>
          <RevealButton revealed={revealed} onToggle={toggle} label="media" />
          <OriginalMedia id={query.data.id} type={query.data.type} revealed={revealed} standalone />
        </>
      )}
    </div>
  )
}
