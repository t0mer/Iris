import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ChevronLeft,
  CircleAlert,
  MessagesSquare,
  RotateCcw,
  Send,
  ShieldOff,
  X,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { KidStack } from '../components/KidAvatar'
import { PageHeader } from '../components/PageHeader'
import { CategoryChips } from '../components/Scores'
import { ClassificationCards } from '../components/ClassificationCards'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { dateTime } from '../lib/format'
import type { AlertDetail as Detail } from '../lib/types'

const STATUS = { new: 'New', acknowledged: 'Seen', dismissed: 'Dismissed' } as const

function reason(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback
}

export function AlertDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: a, isError } = useQuery({
    queryKey: ['alert', id],
    queryFn: () => api<Detail>(`/api/alerts/${id}`),
  })
  const refresh = () => qc.invalidateQueries()
  const setStatus = useMutation({
    mutationFn: (status: string) =>
      api(`/api/alerts/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
    onSuccess: (_d, status) => {
      toast.success(
        status === 'dismissed'
          ? 'Alert dismissed.'
          : status === 'acknowledged'
            ? 'Marked as seen.'
            : 'Alert reopened.',
      )
      return refresh()
    },
    onError: (e) => toast.error(reason(e, 'Could not update the alert. Try again.')),
  })
  const resend = useMutation({
    mutationFn: () => api(`/api/alerts/${id}/resend`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Resending the alert to your WhatsApp.')
      return refresh()
    },
    onError: (e) => toast.error(reason(e, 'Could not resend the alert.')),
  })

  if (isError)
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Alert" />
        <p role="alert" className="rounded-md bg-danger-soft p-4 text-sm text-danger">
          This alert no longer exists. It may have been removed by the retention window.
        </p>
      </div>
    )
  if (!a)
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    )

  const undelivered = a.delivery_status === 'failed'
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Link
        to="/alerts"
        className="inline-flex min-h-10 w-fit items-center gap-1 text-sm font-medium text-primary"
      >
        <ChevronLeft className="size-4 rtl:rotate-180" /> All alerts
      </Link>
      <PageHeader
        title={`Alert for ${a.kid_names.join(' and ')}`}
        description={`${dateTime(a.sent_at)}${a.chat_name ? `, in ${a.chat_name}` : ''}${a.sender_name ? `, from ${a.sender_name}` : ''}`}
      />

      <div className="flex flex-wrap items-center gap-3">
        <KidStack names={a.kid_names} />
        <CategoryChips categories={a.categories} score={a.max_score} />
        <Badge tone={a.status === 'new' ? 'danger' : 'success'}>
          {STATUS[a.status as keyof typeof STATUS] ?? a.status}
        </Badge>
        <MessageFlags
          m={{ id: a.message_id, edited_at: a.edited_at, revoked_at: a.revoked_at }}
          history
        />
      </div>

      {a.redacted ? (
        <div className="flex items-start gap-3 rounded-lg border bg-surface p-5">
          <ShieldOff className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <p>
            The content is withheld because it may involve a minor in a sexual context. Iris does
            not store or show it. Review the chat directly in WhatsApp.
          </p>
        </div>
      ) : (
        <blockquote
          className={cn(
            'rounded-lg border-s-4 border-danger bg-surface p-5 text-lg leading-relaxed',
            revokedClass(a),
          )}
          dir="auto"
        >
          <span className="whitespace-pre-wrap break-words">{a.quote}</span>
        </blockquote>
      )}

      <div className="flex flex-wrap gap-2">
        {a.status === 'new' ? (
          <Button
            variant="primary"
            onClick={() => setStatus.mutate('acknowledged')}
            disabled={setStatus.isPending}
          >
            <Check /> Mark as seen
          </Button>
        ) : (
          <Button
            variant="outline"
            onClick={() => setStatus.mutate('new')}
            disabled={setStatus.isPending}
          >
            <RotateCcw /> Reopen
          </Button>
        )}
        {a.status !== 'dismissed' && (
          <Button
            variant="outline"
            onClick={() => setStatus.mutate('dismissed')}
            disabled={setStatus.isPending}
          >
            <X /> Dismiss
          </Button>
        )}
        <Button asChild variant="outline">
          <Link to={`/messages/${a.message_id}`}>
            <MessagesSquare /> See the conversation
          </Link>
        </Button>
      </div>

      <section
        aria-labelledby="delivery"
        className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-surface p-4"
      >
        <h2 id="delivery" className="sr-only">
          Delivery
        </h2>
        <span className="flex items-center gap-2">
          {undelivered ? (
            <CircleAlert className="size-5 text-danger" />
          ) : (
            <Send className="size-5 text-muted-foreground" />
          )}
          <span className="font-medium">
            {{
              sent: 'Delivered to your WhatsApp',
              failed: 'Not delivered',
              suppressed: 'Held back by the cooldown',
              pending: 'Sending',
            }[a.delivery_status] ?? a.delivery_status}
          </span>
          {a.notified_at && (
            <span className="text-sm text-muted-foreground">{dateTime(a.notified_at)}</span>
          )}
        </span>
        {a.delivery_error && <span className="text-sm text-danger">{a.delivery_error}</span>}
        <Button
          className="ms-auto"
          variant={undelivered ? 'primary' : 'outline'}
          size="sm"
          onClick={() => resend.mutate()}
          disabled={resend.isPending}
        >
          <Send /> Send again
        </Button>
      </section>

      <section aria-labelledby="how" className="flex flex-col gap-3">
        <h2 id="how" className="text-lg font-semibold">
          How Iris decided
        </h2>
        <ClassificationCards items={a.classifications} />
      </section>
    </div>
  )
}
