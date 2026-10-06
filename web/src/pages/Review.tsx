import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ListChecks, MessagesSquare, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState } from '../components/EmptyState'
import { KidStack } from '../components/KidAvatar'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { MessageBody } from '../components/MessageBody'
import { PageHeader } from '../components/PageHeader'
import { Scores } from '../components/Scores'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { cn } from '../lib/cn'
import { relativeTime } from '../lib/format'
import type { ReviewPage } from '../lib/types'
import { QueryError } from '../components/QueryError'

export function Review() {
  const qc = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['review'],
    queryFn: () => api<ReviewPage>('/api/review'),
  })
  const resolve = useMutation({
    mutationFn: (v: { id: number; resolution: 'safe' | 'harmful' }) =>
      api(`/api/review/${v.id}`, {
        method: 'POST',
        body: JSON.stringify({ resolution: v.resolution }),
      }),
    onSuccess: (_d, v) => {
      toast.success(
        v.resolution === 'safe' ? 'Marked safe.' : 'Marked harmful. An alert was created.',
      )
      return qc.invalidateQueries()
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : 'Could not save your decision. Try again.'),
  })
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="Review"
        description="Messages Iris could not decide on, even with the chat around them. Your call."
      />
      {isLoading && <Skeleton className="h-40" />}
      {isError && <QueryError what="the review queue" onRetry={() => void refetch()} />}
      {data && data.items.length === 0 && (
        <div className="rounded-lg border bg-surface">
          <EmptyState icon={ListChecks} title="Nothing to review">
            When Iris cannot tell whether a message is harmful, it waits here for you.
          </EmptyState>
        </div>
      )}
      <ul className="flex flex-col gap-4">
        {data?.items.map(({ message: m, classifications }) => (
          <li
            key={m.id}
            className={cn(
              'flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5',
              revokedClass(m, 'row'),
            )}
          >
            <div className="flex flex-wrap items-center gap-3">
              <KidStack names={m.kids.map((k) => k.kid_name)} />
              <span className="font-medium">{m.kids.map((k) => k.kid_name).join(' and ')}</span>
              {m.chat_name && (
                <span className="text-sm text-muted-foreground">in {m.chat_name}</span>
              )}
              <span className="ms-auto text-xs text-muted-foreground">
                {relativeTime(m.sent_at)}
              </span>
            </div>
            <p className="max-w-prose text-lg leading-relaxed">
              {m.sender_name && (
                <span className="me-2 text-sm text-muted-foreground">{m.sender_name}:</span>
              )}
              <MessageBody m={m} />
            </p>
            <div className="flex flex-wrap items-center gap-1.5 empty:hidden">
              <MessageFlags m={m} history />
            </div>
            {classifications.slice(-1).map((c) => (
              <details key={c.id} className="group rounded-md bg-surface-2/60 p-3">
                <summary className="cursor-pointer text-sm font-medium">Why it is unclear</summary>
                <div className="mt-3">
                  <Scores scores={c.scores} min={0.05} />
                </div>
              </details>
            ))}
            <div className="grid grid-cols-2 gap-2 sm:flex">
              <Button
                variant="outline"
                size="lg"
                disabled={resolve.isPending}
                onClick={() => resolve.mutate({ id: m.id, resolution: 'safe' })}
              >
                <Check /> Mark safe
              </Button>
              <Button
                variant="danger"
                size="lg"
                disabled={resolve.isPending}
                onClick={() => resolve.mutate({ id: m.id, resolution: 'harmful' })}
              >
                <ShieldAlert /> Mark harmful
              </Button>
              <Button asChild variant="ghost" size="lg" className="col-span-2 sm:col-span-1">
                <Link to={`/messages/${m.id}`}>
                  <MessagesSquare /> See the conversation
                </Link>
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
