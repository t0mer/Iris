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
import { MediaPlayer } from '../components/MediaPlayer'
import { Concealed, RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { KidStack } from '../components/KidAvatar'
import { cn } from '../lib/cn'
import { PageHeader } from '../components/PageHeader'
import { CategoryChips } from '../components/Scores'
import { ClassificationCards } from '../components/ClassificationCards'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { dateTime } from '../lib/format'
import { categoryLabel, strings, t } from '../lib/i18n'
import type { AlertDetail as Detail } from '../lib/types'

const STATUS = {
  new: strings.alertDetail.statusNew,
  acknowledged: strings.alertDetail.statusSeen,
  dismissed: strings.alertDetail.statusDismissed,
} as const

function reason(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback
}

export function AlertDetail() {
  const { id } = useParams()
  const { revealed, toggle } = useReveal(id)
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
          ? t('alertDetail.dismissedToast')
          : status === 'acknowledged'
            ? t('alertDetail.seenToast')
            : t('alertDetail.reopenedToast'),
      )
      return refresh()
    },
    onError: (e) => toast.error(reason(e, t('alertDetail.updateFailed'))),
  })
  const resend = useMutation({
    mutationFn: () => api(`/api/alerts/${id}/resend`, { method: 'POST' }),
    onSuccess: () => {
      toast.success(t('alertDetail.resendingToast'))
      return refresh()
    },
    onError: (e) => toast.error(reason(e, t('alertDetail.resendFailed'))),
  })

  if (isError)
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title={t('alertDetail.heading')} />
        <p role="alert" className="rounded-md bg-danger-soft p-4 text-sm text-danger">
          {t('alertDetail.gone')}
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
        <ChevronLeft className="size-4 rtl:rotate-180" /> {t('alertDetail.allAlerts')}
      </Link>
      <PageHeader
        title={t('alertDetail.titleFor', strings.names.join(a.kid_names))}
        description={`${dateTime(a.sent_at)}${a.chat_name ? t('alertDetail.inChat', a.chat_name) : ''}${a.sender_name ? t('alertDetail.fromSender', a.sender_name) : ''}`}
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
          <div className="flex flex-col gap-2">
            <p className="font-medium">{t('alertDetail.withheldTitle')}</p>
            <p>
              {t(
                'alertDetail.withheldBody',
                a.categories.map(categoryLabel).join(', '),
                a.max_score.toFixed(2),
              )}
            </p>
            <p className="text-sm text-muted-foreground">{t('alertDetail.withheldOnlyDetails')}</p>
          </div>
        </div>
      ) : a.quote === null ? (
        <div className="flex items-start gap-3 rounded-lg border bg-surface p-5">
          <ShieldOff className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <div className="flex flex-col gap-2">
            <p className="font-medium">{t('alertDetail.keptOutTitle')}</p>
            <p>{t('alertDetail.keptOutBody')}</p>
            <Button asChild variant="outline" className="w-fit">
              <Link to={`/messages/${a.message_id}`}>
                <MessagesSquare /> {t('alertDetail.readInConversation')}
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">{t('alertDetail.theMessage')}</h2>
            <RevealButton revealed={revealed} onToggle={toggle} />
          </div>
          <blockquote
            className={cn(
              'rounded-lg border-s-4 border-danger bg-surface p-5 text-lg leading-relaxed',
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
        </>
      )}

      {a.media && !a.redacted && (
        <section aria-labelledby="kept" className="flex flex-col gap-3">
          <h2 id="kept" className="text-lg font-semibold">
            {t('alertDetail.keptMedia')}
          </h2>
          <MediaPlayer media={a.media} revealed={revealed} />
          <Link
            to={`/media/${a.media.id}`}
            className="w-fit text-sm font-medium text-primary hover:underline"
          >
            {t('alertDetail.openOwnPage')}
          </Link>
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        {a.status === 'new' ? (
          <Button
            variant="primary"
            onClick={() => setStatus.mutate('acknowledged')}
            disabled={setStatus.isPending}
          >
            <Check /> {t('alertDetail.markSeen')}
          </Button>
        ) : (
          <Button
            variant="outline"
            onClick={() => setStatus.mutate('new')}
            disabled={setStatus.isPending}
          >
            <RotateCcw /> {t('alertDetail.reopen')}
          </Button>
        )}
        {a.status !== 'dismissed' && (
          <Button
            variant="outline"
            onClick={() => setStatus.mutate('dismissed')}
            disabled={setStatus.isPending}
          >
            <X /> {t('alertDetail.dismiss')}
          </Button>
        )}
        <Button asChild variant="outline">
          <Link to={`/messages/${a.message_id}`}>
            <MessagesSquare /> {t('alertDetail.seeConversation')}
          </Link>
        </Button>
      </div>

      <section
        aria-labelledby="delivery"
        className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-surface p-4"
      >
        <h2 id="delivery" className="sr-only">
          {t('alertDetail.delivery')}
        </h2>
        <span className="flex items-center gap-2">
          {undelivered ? (
            <CircleAlert className="size-5 text-danger" />
          ) : (
            <Send className="size-5 text-muted-foreground" />
          )}
          <span className="font-medium">
            {{
              sent: t('alertDetail.deliveredToWhatsapp'),
              failed: t('alertDetail.notDelivered'),
              suppressed: t('alertDetail.heldByCooldown'),
              pending: t('alertDetail.sending'),
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
          <Send /> {t('alertDetail.sendAgain')}
        </Button>
      </section>

      <section aria-labelledby="how" className="flex flex-col gap-3">
        <h2 id="how" className="text-lg font-semibold">
          {t('alertDetail.howDecided')}
        </h2>
        <ClassificationCards items={a.classifications} />
      </section>
    </div>
  )
}
