import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BrainCircuit, MessagesSquare, SkipForward } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { useMe } from '../lib/auth'
import { relativeTime } from '../lib/format'
import { useUrlState } from '../lib/urlState'
import type { ReviewPage } from '../lib/types'
import { RevealableMessage } from '../components/MessageBody'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { QueryError } from '../components/QueryError'
import { Skeleton } from '../components/ui/skeleton'
import { Button } from '../components/ui/button'

export function IrisReview() {
  const { page, update } = useUrlState()
  const { data: me } = useMe()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['review', 'ai', page],
    queryFn: () => api<ReviewPage>(`/api/review?view=ai&page=${page}&page_size=25`),
    refetchInterval: 15_000,
  })
  const skip = useMutation({
    mutationFn: (id: number) =>
      api<{ human_review_view: string }>(`/api/review/${id}/skip-ai`, { method: 'POST' }),
    onSuccess: (result) => {
      toast.success(
        result.human_review_view === 'responses'
          ? 'AI skipped; existing human decision kept.'
          : 'Moved to human Review.',
        {
          action: {
            label: 'Open Review',
            onClick: () => navigate(`/review?view=${result.human_review_view}`),
          },
        },
      )
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="IrisReview"
        description="Messages queued for AI or being checked. Safe and Harmful decisions belong in human Review."
        actions={<BrainCircuit aria-label="AI review" className="size-7 text-primary" />}
      />
      {data && (
        <p className="text-sm text-muted-foreground" role="status">
          {data.total} messages in the AI queue
        </p>
      )}
      {isLoading && <Skeleton className="h-40" />}
      {isError && <QueryError what="AI review queue" onRetry={() => void refetch()} />}
      {data?.total === 0 && <p className="text-muted-foreground">No messages waiting for AI.</p>}
      <ul className="flex flex-col gap-4">
        {data?.items.map(({ message: m }) => (
          <li key={m.id} className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {m.kids.map((k) => k.kid_name).join(' and ')}
                {m.chat_name ? ` · ${m.chat_name}` : ''}
              </span>
              <span className="text-xs text-muted-foreground">{relativeTime(m.sent_at)}</span>
            </div>
            <div role="status" className="flex items-center gap-2 text-sm text-primary">
              <BrainCircuit
                aria-label="AI thinking"
                className="size-5 animate-pulse motion-reduce:animate-none"
              />
              {m.status === 'processing' ? 'AI is thinking…' : 'Waiting for AI…'}
            </div>
            <RevealableMessage m={m} showMedia />
            {m.sender_name && (
              <p dir="auto" className="text-xs text-muted-foreground">
                From {m.sender_name}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {['admin', 'parent'].includes(me?.role || '') && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={skip.isPending}
                  onClick={() => skip.mutate(m.id)}
                >
                  <SkipForward /> Skip AI → Human review
                </Button>
              )}
              <Link
                to={`/messages/${m.id}`}
                className="flex items-center gap-1 text-sm text-primary"
              >
                <MessagesSquare className="size-4" /> Chat
              </Link>
            </div>
          </li>
        ))}
      </ul>
      <Link to="/review" className="text-sm text-primary">
        Open human Review
      </Link>
      {data && (
        <Pagination
          page={page}
          pageSize={25}
          total={data.total}
          onPage={(p) => update({ page: String(p) })}
          noun={['message', 'messages']}
        />
      )}
    </div>
  )
}
