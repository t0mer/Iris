import { t } from '../lib/i18n'
import { useMe } from '../lib/auth'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft,
  CircleAlert,
  MessagesSquare,
  RotateCcw,
  Send,
  ShieldOff,
  X,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { toast } from '../lib/notify'
import { OriginalMedia } from '../components/OriginalMedia'
import { MediaPlayer } from '../components/MediaPlayer'
import { Concealed, RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { KidStack } from '../components/KidAvatar'
import { cn } from '../lib/cn'
import { PageHeader } from '../components/PageHeader'
import { QueryError } from '../components/QueryError'
import { CategoryChips } from '../components/Scores'
import { ClassificationCards } from '../components/ClassificationCards'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { dateTime } from '../lib/format'
import type { AlertDetail as Detail } from '../lib/types'
import { useEffect, useRef } from 'react'

const STATUS = { new: 'Unseen', acknowledged: 'Seen', dismissed: 'Dismissed' } as const

function reason(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback
}

export function AlertDetail() {
  const { id } = useParams()
  const { revealed, toggle } = useReveal(id)
  const qc = useQueryClient()
  const { data: me, isError: authError, refetch: refetchMe } = useMe()
  const canAct = me?.role === 'admin' || me?.role === 'parent'
  const opened = useRef('')
  const {
    data: a,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['alert', me?.id, id],
    queryFn: () => api<Detail>(`/api/alerts/${id}`),
    enabled: !!me,
  })
  const refresh = () => qc.invalidateQueries()
  const seen = useMutation({
    mutationFn: (value: boolean) =>
      api<Detail>(`/api/alerts/${id}/seen`, {
        method: 'POST',
        body: JSON.stringify({ seen: value }),
      }),
    onSuccess: (result, value) => {
      qc.setQueryData<Detail>(['alert', me?.id, id], (previous) =>
        previous
          ? {
              ...previous,
              status: value
                ? result.status === 'dismissed'
                  ? 'dismissed'
                  : 'acknowledged'
                : 'new',
              seen_at: result.seen_at,
            }
          : previous,
      )
      void qc.invalidateQueries({ queryKey: ['alerts'] })
      void qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (e) => toast.error(reason(e, 'Could not save your read status.')),
  })
  useEffect(() => {
    const key = `${me?.id}:${id}`
    if (a && me && a.status === 'new' && opened.current !== key) {
      opened.current = key
      seen.mutate(true)
    }
  }, [a, me, id, seen])
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

  if (isError || authError)
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title={t('Alert')} />
        {error instanceof ApiError && error.status === 404 ? (
          <p role="alert" className="rounded-md bg-danger-soft p-4 text-sm text-danger">
            {t('This alert no longer exists. It may have been removed by the retention window.')}
          </p>
        ) : (
          <QueryError
            what="this alert"
            onRetry={() => void (authError ? refetchMe() : refetch())}
          />
        )}
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
        <ChevronLeft className="size-4 rtl:rotate-180" /> {t('All alerts')}
      </Link>
      <PageHeader
        title={t('Alert for {value0}', { value0: a.kid_names.join(' and ') })}
        description={`${dateTime(a.sent_at)}${a.chat_name ? t(', in {value0}', { value0: a.chat_name }) : ''}${a.sender_name ? t(', from {value0}', { value0: a.sender_name }) : ''}`}
      />

      {a.verdict === 'review' && (
        <p className="rounded border p-3 text-sm">
          {t('Needs parent review; this is not a harmful verdict.')} {a.review_reason}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <KidStack names={a.kid_names} />
        <CategoryChips categories={a.categories} score={a.max_score} />
        <Badge tone={a.status === 'new' ? 'danger' : 'success'}>
          {t(STATUS[a.status as keyof typeof STATUS] ?? a.status)}
        </Badge>
        <MessageFlags
          m={{ id: a.message_id, edited_at: a.edited_at, revoked_at: a.revoked_at }}
          history
        />
      </div>

      {a.redacted ? (
        <div className="flex items-start gap-3 rounded-lg border bg-surface p-5">
          <ShieldOff className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <div className="flex flex-col gap-2">
            <p className="font-medium">{t('Withheld on purpose, so there is nothing to show')}</p>
            <p>
              {t('Iris detected')} {a.categories.join(', ')} ({a.max_score.toFixed(2)}
              {t(
                ') in a message that may involve a minor in a sexual context. It never stored the content, because keeping it could be illegal, so it cannot be shown here.',
              )}
            </p>
            <p className="text-sm text-muted-foreground">
              {t(
                'Only the details above are kept. To see what was sent, open the chat directly in WhatsApp.',
              )}
            </p>
          </div>
        </div>
      ) : a.quote === null ? (
        <div className="flex items-start gap-3 rounded-lg border bg-surface p-5">
          <ShieldOff className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <div className="flex flex-col gap-2">
            <p className="font-medium">{t('Kept out of this alert')}</p>
            <p>
              {t(
                'The text may involve a minor, so it was not copied into the alert or sent to your WhatsApp. It is kept so you can read it and decide.',
              )}
            </p>
            <Button asChild variant="outline" className="w-fit">
              <Link to={`/messages/${a.message_id}`}>
                <MessagesSquare /> {t('Read it in the conversation')}
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-medium">{t('The message')}</h2>
            <RevealButton revealed={revealed} onToggle={toggle} />
          </div>
          <div className="rounded-3xl border bg-surface-2/40 p-4 sm:p-6">
            <div className="mb-4 flex items-center gap-3 border-b pb-3">
              <MessagesSquare className="size-5 text-success" />
              <div>
                <p className="font-medium">{a.chat_name || 'WhatsApp conversation'}</p>
                <p className="text-xs text-muted-foreground">
                  {a.sender_name || 'Message'} · {dateTime(a.sent_at)}
                </p>
              </div>
            </div>
            <blockquote
              className={cn(
                'rounded-2xl rounded-ss-sm border border-success/20 bg-success-soft/40 p-5 text-[17px] font-normal leading-relaxed shadow-sm',
                revokedClass(a),
              )}
              dir="auto"
            >
              <span className="whitespace-pre-wrap break-words">
                <Concealed revealed={revealed} length={a.quote?.length}>
                  {a.quote}
                </Concealed>
              </span>
            </blockquote>
          </div>
        </>
      )}

      {!a.redacted &&
        !a.media &&
        ['image', 'sticker', 'video', 'voice', 'audio', 'document'].includes(a.message_type) && (
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">
              {t('Original')}{' '}
              {a.message_type === 'sticker'
                ? t('sticker')
                : a.message_type === 'document'
                  ? t('document')
                  : t('media')}
            </h2>
            <OriginalMedia
              key={a.message_id}
              id={a.message_id}
              type={a.message_type}
              revealed={revealed}
            />
          </section>
        )}
      {a.sending_server && (
        <p className="text-xs text-muted-foreground">
          {t('Sending server:')} <span dir="ltr">{a.sending_server}</span>
        </p>
      )}
      {!!a.response_notes?.length && (
        <section className="rounded-lg border bg-surface p-5">
          <h2 className="mb-3 text-lg font-medium">{t('Parent response notes')}</h2>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('The first accepted response is final.')}
          </p>
          <ul className="flex flex-col gap-3">
            {a.response_notes.map((note, i) => (
              <li key={i} className="text-sm">
                <p>{note.note}</p>
                <time className="text-xs text-muted-foreground">{dateTime(note.created_at)}</time>
              </li>
            ))}
          </ul>
        </section>
      )}
      {a.media && !a.redacted && (
        <section aria-labelledby="kept" className="flex flex-col gap-3">
          <h2 id="kept" className="text-lg font-medium">
            {t('Kept media')}
          </h2>
          <MediaPlayer media={a.media} revealed={revealed} />
          <Link
            to={`/media/${a.media.id}`}
            className="w-fit text-sm font-medium text-primary hover:underline"
          >
            {t('Open on its own page')}
          </Link>
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          title={t('Mark this alert unread for your account')}
          onClick={() => seen.mutate(false)}
          disabled={seen.isPending || !me}
        >
          <RotateCcw /> {t('Mark unseen')}
        </Button>
        {a.status !== 'dismissed' && (
          <Button
            variant="outline"
            size="sm"
            title={t('Dismiss this alert')}
            onClick={() => setStatus.mutate('dismissed')}
            disabled={setStatus.isPending || !canAct}
          >
            <X /> {t('Dismiss')}
          </Button>
        )}
        <Button asChild variant="ghost" size="sm">
          <Link
            to={`/messages/${a.message_id}`}
            aria-label={t('See the conversation')}
            title={t('Open the full conversation')}
          >
            <MessagesSquare /> {t('Chat')}
          </Link>
        </Button>
      </div>

      <section
        aria-labelledby="delivery"
        className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-surface p-4"
      >
        <h2 id="delivery" className="sr-only">
          {t('Delivery')}
        </h2>
        <span className="flex items-center gap-2">
          {undelivered ? (
            <CircleAlert className="size-5 text-danger" />
          ) : (
            <Send className="size-5 text-muted-foreground" />
          )}
          <span className="font-medium">
            {{
              sent: 'Delivered to all recipients',
              partial: 'Delivered to some recipients',
              failed: 'Not delivered',
              paused: 'Held because monitoring is paused',
              suppressed: 'Held back by the cooldown',
              pending: 'Queued',
            }[a.delivery_status] ?? a.delivery_status}
          </span>
          {a.notified_at && (
            <span className="text-sm text-muted-foreground">{dateTime(a.notified_at)}</span>
          )}
        </span>
        {a.delivery_error && (
          <span
            className={
              a.delivery_error.startsWith('Queued for sending capacity')
                ? 'text-sm text-muted-foreground'
                : 'text-sm text-danger'
            }
          >
            {a.delivery_error}
          </span>
        )}
        <Button
          className="ms-auto"
          variant={undelivered ? 'primary' : 'outline'}
          size="sm"
          onClick={() => resend.mutate()}
          disabled={resend.isPending || !canAct}
        >
          <Send /> {t('Send again')}
        </Button>
        {(a.recipient_delivery?.length ?? 0) > 0 && (
          <ul className="w-full space-y-1 text-sm">
            {a.recipient_delivery?.map((recipient, index) => (
              <li key={index}>
                {recipient.recipient}:{' '}
                <span
                  className={recipient.status === 'delivered' ? 'text-success' : 'text-warning'}
                >
                  {recipient.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="how" className="flex flex-col gap-3">
        <h2 id="how" className="text-lg font-medium">
          {t('How Iris decided')}
        </h2>
        <ClassificationCards
          items={a.classifications}
          emptyReason={
            a.verdict === 'review'
              ? a.review_reason?.startsWith('Legacy review:')
                ? 'No classification record was saved for this older message. Parent review is required; it is not waiting for an automatic check.'
                : a.review_reason ||
                  'Iris could not complete this check. Parent review is required.'
              : undefined
          }
        />
      </section>
    </div>
  )
}
