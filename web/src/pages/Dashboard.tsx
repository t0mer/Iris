import { t } from '../lib/i18n'
import { he } from '../lib/he'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  BellRing,
  ListChecks,
  ServerCrash,
  Settings,
  Smartphone,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ActivityChart } from '../components/ActivityChart'
import { AlertRow } from '../components/AlertRow'
import { RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { EmptyState } from '../components/EmptyState'
import { IrisRing } from '../components/IrisRing'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { fileSize } from '../lib/format'
import type { AlertPage, Stats, Timeline } from '../lib/types'
import { QueryError } from '../components/QueryError'

const REFRESH_MS = 60_000

interface Item {
  icon: LucideIcon
  to: string
  action: string
  text: ReactNode
  tone: 'danger' | 'warning'
}

function attentionItems(s: Stats): Item[] {
  const items: Item[] = []
  if ((s.children ?? s.instances) === 0)
    items.push({
      icon: Smartphone,
      to: '/instances',
      action: he('Add a child'),
      tone: 'warning',
      text: he('No child phone is configured. Iris cannot monitor children yet.'),
    })
  if (s.parent_recipients === 0)
    items.push({
      icon: Settings,
      to: '/settings?tab=Alerts',
      action: he('Add parents'),
      tone: 'warning',
      text: he('No parent recipients are configured. Add a parent phone number to receive alerts.'),
    })
  if (s.alert_sender_configured === false)
    items.push({
      icon: Smartphone,
      to: '/settings?tab=Alerts',
      action: he('Set alert phone'),
      tone: 'warning',
      text: he(
        'No alert phone is set. Connect a sender phone and select it to send alerts to parents.',
      ),
    })
  const alerts = s.alerts_by_status['new'] ?? 0
  if (alerts > 0)
    items.push({
      icon: BellRing,
      to: '/alerts?status=new',
      action: he('Open alerts'),
      tone: 'danger',
      text: t('dashboard.newAlertsToRead', alerts),
    })
  if (s.review_queue > 0)
    items.push({
      icon: ListChecks,
      to: '/review',
      action: he('Review'),
      tone: 'warning',
      text: he('{n} messages Iris could not classify', { n: s.review_queue }),
    })
  if (!s.delivery_configured)
    items.push({
      icon: Settings,
      to: '/settings?tab=Alerts',
      action: he('Set up delivery'),
      tone: 'warning',
      text: he('Alert delivery is not configured, so alerts are recorded but not sent.'),
    })
  const undelivered = s.alerts_by_delivery['failed'] ?? 0
  if ((s.unavailable_instances ?? 0) > 0)
    items.push({
      icon: ServerCrash,
      to: '/instances',
      action: he('Check sessions'),
      tone: 'danger',
      text: he(
        'A monitored phone or the alert sender is disconnected or unreachable. Monitoring or delivery may have stopped.',
      ),
    })
  if (s.sender_is_recipient)
    items.push({
      icon: Smartphone,
      to: '/settings?tab=Alerts',
      action: he('Check recipients'),
      tone: 'warning',
      text: he(
        'The sender is also a parent recipient. Messages to yourself may not notify you; use a separate sender phone for reliable parent notifications.',
      ),
    })
  if ((s.alerts_by_delivery['partial'] ?? 0) > 0)
    items.push({
      icon: BellRing,
      to: '/alerts',
      action: he('Check delivery'),
      tone: 'warning',
      text: he('Some alerts reached only part of the parent recipient list.'),
    })
  if (s.delivery_configured && undelivered > 0)
    items.push({
      icon: ServerCrash,
      to: '/alerts',
      action: he('See alerts'),
      tone: 'danger',
      text: he('{n} alerts not delivered to your WhatsApp', { n: undelivered }),
    })
  if (s.failed_jobs > 0)
    items.push({
      icon: Activity,
      to: '/jobs',
      action: he('See why'),
      tone: 'warning',
      text: t('dashboard.jobsFailed', s.failed_jobs),
    })
  if (s.silent_instances > 0)
    items.push({
      icon: Smartphone,
      to: '/instances',
      action: he('Check setup'),
      tone: 'warning',
      text: he(
        s.monitoring_window_minutes
          ? '{n} phones with no messages in the configured window'
          : '{n} phones that have never received messages',
        { n: s.silent_instances },
      ),
    })
  return items
}

function headline(s: Stats, items: Item[]) {
  const alerts = s.alerts_by_status['new'] ?? 0
  const review = s.review_queue
  if (alerts + review > 0) {
    const parts = [
      alerts > 0 && t('dashboard.alertsCount', alerts),
      review > 0 && t('dashboard.toReview', review),
    ].filter(Boolean)
    return {
      title: he('{parts} need your attention', { parts: parts.join(he(' and ')) }),
      sub: he('Start with the newest alert.'),
    }
  }
  if (items.length > 0)
    return {
      title: he('Needs attention'),
      sub: he('Monitoring or alert delivery needs setting up or fixing, below.'),
    }
  return {
    title: he('All quiet'),
    sub:
      s.messages_today > 0
        ? he('Iris checked {n} messages today and did not flag harmful content.', {
            n: s.messages_today,
          })
        : he('Iris is watching. Nothing has come in today yet.'),
  }
}

function Stat({
  label,
  value,
  to,
  note,
}: {
  label: string
  value: number
  to?: string
  note?: string
}) {
  // <dl> may only hold <dt>/<dd> groups, so a linked stat puts its (stretched) link inside the <dd>.
  return (
    <div className="relative flex flex-col-reverse gap-1.5 px-4 py-3 hover:bg-surface-2/60 sm:px-5">
      <dt className="text-sm text-muted-foreground">
        {label}
        {note && <span className="block text-xs">{note}</span>}
      </dt>
      <dd className="tabular text-2xl font-semibold leading-none">
        {to ? (
          <Link to={to} aria-label={`${label}: ${value}`} className="after:absolute after:inset-0">
            {value}
          </Link>
        ) : (
          value
        )}
      </dd>
    </div>
  )
}

function Loading() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label={he('Loading the dashboard')}>
      <Skeleton className="h-52 rounded-lg" />
      <Skeleton className="h-64 rounded-lg" />
      <Skeleton className="h-40 rounded-lg" />
    </div>
  )
}

export function Dashboard() {
  const { revealed, toggle } = useReveal()
  const stats = useQuery({
    queryKey: ['stats'],
    queryFn: () => api<Stats>('/api/stats'),
    refetchInterval: REFRESH_MS,
  })
  const timeline = useQuery({
    queryKey: ['timeline'],
    queryFn: () => api<Timeline>('/api/stats/timeline?days=14'),
    refetchInterval: REFRESH_MS,
  })
  const alerts = useQuery({
    queryKey: ['alerts', 'recent'],
    queryFn: () => api<AlertPage>('/api/alerts?page_size=5'),
    refetchInterval: REFRESH_MS,
  })

  if (stats.isError)
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title={he('Home')} />
        <p role="alert" className="rounded-md bg-danger-soft p-4 text-sm text-danger">
          {he('Could not load the dashboard. Check that Iris is running, then reload the page.')}
        </p>
      </div>
    )
  if (!stats.data) return <Loading />

  const s = stats.data
  const items = attentionItems(s)
  const { title, sub } = headline(s, items)
  const days = timeline.data?.days ?? []

  return (
    <div className="flex flex-col gap-8">
      <PageHeader title={he('Home')} />

      <section
        aria-label={he('Status')}
        className="flex flex-col items-center gap-6 rounded-xl border bg-surface p-6 sm:flex-row sm:p-8"
      >
        <IrisRing alerts={s.alerts_by_status['new'] ?? 0} review={s.review_queue} />
        <div className="flex min-w-0 flex-1 flex-col gap-4 text-center sm:text-start">
          <div className="flex flex-col gap-1.5">
            <p className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</p>
            <p className="max-w-prose text-muted-foreground">{sub}</p>
          </div>
          <dl className="grid grid-cols-2 divide-x divide-y rounded-md border sm:grid-cols-3 rtl:divide-x-reverse">
            <Stat label={he('Messages today')} value={s.messages_today} to="/messages" />
            <Stat label={he('Last 7 days')} value={s.messages_7d} to="/messages" />
            <Stat label={he('In the queue')} value={s.queue_depth} />
            <Stat label={he('Children')} value={s.children ?? s.instances} to="/instances" />
            <Stat
              label={he('Parents')}
              value={s.parent_recipients ?? 0}
              to="/settings?tab=Alerts"
              note={he('Alert recipients')}
            />
            <Stat
              label={he('Alert phones')}
              value={s.alert_phones ?? 0}
              to="/settings?tab=Alerts"
              note={he('Sender connections')}
            />
            {((s.media_policy && s.media_policy !== 'off') || (s.media_files ?? 0) > 0) && (
              <Stat
                label={he('Media kept')}
                value={s.media_files ?? 0}
                note={fileSize(s.media_bytes ?? 0)}
              />
            )}
          </dl>
        </div>
      </section>

      {items.length > 0 && (
        <section aria-labelledby="attention" className="flex flex-col gap-3">
          <h2 id="attention" className="text-lg font-semibold">
            {he('Needs attention')}
          </h2>
          <ul className="divide-y rounded-lg border bg-surface">
            {items.map((it) => (
              <li key={it.text as string} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span
                  className={`grid size-9 shrink-0 place-items-center rounded-full ${it.tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-warning-soft text-warning'}`}
                >
                  <it.icon className="size-5" />
                </span>
                <span className="min-w-0 flex-1 basis-56">{it.text}</span>
                <Link
                  to={it.to}
                  className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-primary hover:bg-primary-soft"
                >
                  {it.action}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section
        aria-labelledby="activity"
        className="flex flex-col gap-3 rounded-lg border bg-surface p-4 sm:p-5"
      >
        <h2 id="activity" className="text-lg font-semibold">
          {he('Activity, last 14 days')}
        </h2>
        {timeline.isError ? (
          <QueryError what="the activity chart" onRetry={() => void timeline.refetch()} />
        ) : timeline.isLoading ? (
          <Skeleton className="h-52" />
        ) : days.length > 0 ? (
          <ActivityChart days={days} />
        ) : (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {he('The chart appears once Iris has seen some messages.')}
          </p>
        )}
      </section>

      <section aria-labelledby="recent" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 id="recent" className="text-lg font-semibold">
            {he('Recent alerts')}
          </h2>
          <div className="flex items-center gap-1">
            <RevealButton revealed={revealed} onToggle={toggle} />
            <Link
              to="/alerts"
              className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-primary hover:bg-primary-soft"
            >
              {he('See all')}
            </Link>
          </div>
        </div>
        <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
          {alerts.data?.items.map((a) => (
            <AlertRow key={a.id} alert={a} revealed={revealed} />
          ))}
          {alerts.data && alerts.data.items.length === 0 && (
            <li>
              <EmptyState icon={BellRing} title={he('No alerts yet')}>
                {he(
                  'When a message needs your attention, Iris lists it here and sends it to your WhatsApp.',
                )}
              </EmptyState>
            </li>
          )}
        </ul>
      </section>
    </div>
  )
}
