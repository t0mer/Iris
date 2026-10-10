import { useMe } from '../lib/auth'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, RotateCw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ClassificationCards } from '../components/ClassificationCards'
import { KidStack } from '../components/KidAvatar'
import { Failure, MessageBody, VerdictBadge } from '../components/MessageBody'
import { MediaPlayer } from '../components/MediaPlayer'
import { OriginalMedia } from '../components/OriginalMedia'
import { RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { PageHeader } from '../components/PageHeader'
import { TypeIcon } from '../components/TypeIcon'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { cn } from '../lib/cn'
import { dateTime } from '../lib/format'
import type { Message, MessageDetail } from '../lib/types'
import { QueryError } from '../components/QueryError'

export function MessageContext() {
  const { id } = useParams()
  const { revealed, toggle } = useReveal(id)
  const qc = useQueryClient()
  const { data: me } = useMe()
  const canAct = me?.role === 'admin' || me?.role === 'parent'
  const detailQuery = useQuery({
    queryKey: ['message', id],
    queryFn: () => api<MessageDetail>(`/api/messages/${id}`),
  })
  const detail = detailQuery.data
  const contextQuery = useQuery({
    queryKey: ['message-context', id],
    queryFn: () => api<Message[]>(`/api/messages/${id}/context`),
  })
  const context = contextQuery.data
  const target = useRef<HTMLLIElement>(null)
  const panel = useRef<HTMLOListElement>(null)
  // Centre the message inside the chat panel only; the page itself must not jump.
  useEffect(() => {
    const p = panel.current
    const t = target.current
    if (p && t) p.scrollTop = t.offsetTop - p.offsetTop - p.clientHeight / 2 + t.clientHeight / 2
  }, [context])
  const reprocess = useMutation({
    mutationFn: () => api(`/api/messages/${id}/reprocess`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Checking this message again.')
      return qc.invalidateQueries()
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : 'Could not re-check the message.'),
  })

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Link
        to="/messages"
        className="inline-flex min-h-10 w-fit items-center gap-1 text-sm font-medium text-primary"
      >
        <ChevronLeft className="size-4 rtl:rotate-180" /> All messages
      </Link>
      <PageHeader
        title={detail?.chat_name ?? (detail?.is_group ? 'Group conversation' : 'Conversation')}
        description={
          detail
            ? `Watched on ${detail.kids.map((k) => k.kid_name).join(' and ')}'s phone`
            : undefined
        }
        actions={
          detail ? (
            <>
              <RevealButton revealed={revealed} onToggle={toggle} />
              {!detail.redacted && (
                <Button
                  variant="outline"
                  onClick={() => reprocess.mutate()}
                  disabled={reprocess.isPending || !canAct}
                >
                  <RotateCw /> Check again
                </Button>
              )}
            </>
          ) : undefined
        }
      />
      {detail && (
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <KidStack names={detail.kids.map((k) => k.kid_name)} />
          <VerdictBadge m={detail} />
          <MessageFlags m={detail} history />
          <Failure m={detail} />
          {detail.raw_type && (
            <p className="text-xs text-muted-foreground">OpenWA type: {detail.raw_type}</p>
          )}
          {detail.diagnostics && (
            <details className="min-w-0 max-w-full basis-full text-xs text-muted-foreground">
              <summary>Diagnostic metadata</summary>
              <pre className="max-w-full overflow-x-auto">
                {JSON.stringify(detail.diagnostics, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {detail?.media && !detail.redacted && (
        <div className="flex flex-col gap-2">
          <MediaPlayer media={detail.media} revealed={revealed} />
        </div>
      )}
      {detail &&
        !detail.media &&
        !detail.redacted &&
        ['sticker', 'video', 'image'].includes(detail.type) && (
          <p className="text-sm text-muted-foreground">
            No retained copy is saved. Show content to view the original media from OpenWA below.
          </p>
        )}

      {!context && !contextQuery.isError && <Skeleton className="h-64" />}
      {(detailQuery.isError || contextQuery.isError) && (
        <QueryError
          what="this conversation"
          onRetry={() => {
            void detailQuery.refetch()
            void contextQuery.refetch()
          }}
        />
      )}
      <ol
        ref={panel}
        tabIndex={0}
        aria-label="Messages in this conversation"
        className="relative flex max-h-[65dvh] flex-col gap-2 overflow-y-auto rounded-lg border bg-surface-2/50 p-3 sm:p-4"
      >
        {context?.map((m) => {
          const isTarget = String(m.id) === id
          return (
            <li
              key={m.id}
              ref={isTarget ? target : undefined}
              aria-current={isTarget ? 'true' : undefined}
              className={cn(
                'flex max-w-[88%] flex-col gap-1 rounded-lg px-3.5 py-2.5 sm:max-w-[75%]',
                m.from_me ? 'self-end bg-primary-soft' : 'self-start border bg-surface',
                isTarget &&
                  (m.revoked_at
                    ? 'ring-2 ring-primary ring-offset-2 ring-offset-surface-2'
                    : 'ring-2 ring-primary'),
                revokedClass(m),
              )}
            >
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <TypeIcon type={m.type} className="size-3.5" />
                {m.sender_name ?? 'Unknown'}, {dateTime(m.sent_at)} · Message #{m.id}
                <time dateTime={m.sent_at} title="Original message timestamp">
                  {new Date(m.sent_at).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </time>
              </span>
              <span className="text-[15px]">
                <MessageBody m={m} revealed={revealed} />
              </span>
              {!m.redacted &&
                !m.revoked_at &&
                ['image', 'sticker', 'video', 'audio', 'voice'].includes(m.type) && (
                  <OriginalMedia key={m.id} id={m.id} type={m.type} revealed={revealed} />
                )}
              <span className="flex flex-wrap items-center gap-1.5 empty:hidden">
                {isTarget && <VerdictBadge m={m} />}
                <MessageFlags m={m} history />
              </span>
            </li>
          )
        })}
      </ol>

      {detail && (
        <section aria-labelledby="how" className="flex flex-col gap-3">
          <h2 id="how" className="text-lg font-semibold">
            How Iris decided
          </h2>
          <ClassificationCards items={detail.classifications} />
        </section>
      )}
    </div>
  )
}
