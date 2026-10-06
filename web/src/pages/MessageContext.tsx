import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, RotateCw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ClassificationCards } from '../components/ClassificationCards'
import { KidStack } from '../components/KidAvatar'
import { Failure, MessageBody, VerdictBadge } from '../components/MessageBody'
import { PageHeader } from '../components/PageHeader'
import { TypeIcon } from '../components/TypeIcon'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { cn } from '../lib/cn'
import { dateTime } from '../lib/format'
import type { Message, MessageDetail } from '../lib/types'

export function MessageContext() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: detail } = useQuery({
    queryKey: ['message', id],
    queryFn: () => api<MessageDetail>(`/api/messages/${id}`),
  })
  const { data: context } = useQuery({
    queryKey: ['message-context', id],
    queryFn: () => api<Message[]>(`/api/messages/${id}/context`),
  })
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
          detail && !detail.redacted ? (
            <Button
              variant="outline"
              onClick={() => reprocess.mutate()}
              disabled={reprocess.isPending}
            >
              <RotateCw /> Check again
            </Button>
          ) : undefined
        }
      />
      {detail && (
        <div className="flex items-center gap-3">
          <KidStack names={detail.kids.map((k) => k.kid_name)} />
          <VerdictBadge m={detail} />
          <Failure m={detail} />
        </div>
      )}

      {!context && <Skeleton className="h-64" />}
      <ol
        ref={panel}
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
                isTarget && 'ring-2 ring-primary',
              )}
            >
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <TypeIcon type={m.type} className="size-3.5" />
                {m.sender_name ?? 'Unknown'}, {dateTime(m.sent_at)}
              </span>
              <span className="text-[15px]">
                <MessageBody m={m} />
              </span>
              {isTarget && <VerdictBadge m={m} />}
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
