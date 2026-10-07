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
  const alerts = s.alerts_by_status['new'] ?? 0
  const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)
  if (alerts > 0)
    items.push({
      icon: BellRing,
      to: '/alerts?status=new',
      action: 'Open alerts',
      tone: 'danger',
      text: `${alerts} new ${plural(alerts, 'alert', 'alerts')} to read`,
    })
  if (s.review_queue > 0)
    items.push({
      icon: ListChecks,
      to: '/review',
      action: 'Review',
      tone: 'warning',
      text: `${s.review_queue} ${plural(s.review_queue, 'message', 'messages')} Iris could not decide`,
    })
  if (!s.delivery_configured)
    items.push({
      icon: Settings,
      to: '/settings',
      action: 'Set up delivery',
      tone: 'warning',
      text: 'Alert delivery is not configured, so alerts are recorded but not sent.',
    })
  const undelivered = s.alerts_by_delivery['failed'] ?? 0
  if (s.delivery_configured && undelivered > 0)
    items.push({
      icon: ServerCrash,
      to: '/alerts',
      action: 'See alerts',
      tone: 'danger',
      text: `${undelivered} ${plural(undelivered, 'alert was', 'alerts were')} not delivered to your WhatsApp`,
    })
  if (s.failed_jobs > 0)
    items.push({
      icon: Activity,
      to: '/jobs',
      action: 'See why',
      tone: 'warning',
      text: `${s.failed_jobs} ${plural(s.failed_jobs, 'job', 'jobs')} failed`,
    })
  if (s.silent_instances > 0)
    items.push({
      icon: Smartphone,
      to: '/instances',
      action: 'Check setup',
      tone: 'warning',
      text: `${s.silent_instances} ${plural(s.silent_instances, 'phone has', 'phones have')} never received a webhook`,
    })
  return items
}

function headline(s: Stats, items: Item[]) {
  const alerts = s.alerts_by_status['new'] ?? 0
  const review = s.review_queue
  if (alerts + review > 0) {
    const parts = [
      alerts > 0 && `${alerts} ${alerts === 1 ? 'alert' : 'alerts'}`,
      review > 0 && `${review} to review`,
    ].filter(Boolean)
    return {
      title: `${parts.join(' and ')} ${alerts + review === 1 ? 'needs' : 'need'} you`,
      sub: 'Start with the newest alert.',
    }
  }
  if (items.length > 0)
    return { title: 'Nothing urgent', sub: 'A few things need setting up or fixing, below.' }
  return {
    title: 'All quiet',
    sub:
      s.messages_today > 0
        ? `Iris checked ${s.messages_today} ${s.messages_today === 1 ? 'message' : 'messages'} today and found nothing to worry about.`
        : 'Iris is watching. Nothing has come in today yet.',
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
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading the dashboard">
      <Skeleton className="h-52 rounded-lg" />
      <Skeleton className="h-64 rounded-lg" />
      <Skeleton className="h-40 rounded-lg" />
    </div>
  )
}

export function Dashboard() {
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
        <PageHeader title="Home" />
        <p role="alert" className="rounded-md bg-danger-soft p-4 text-sm text-danger">
          Could not load the dashboard. Check that Iris is running, then reload the page.
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
      <PageHeader title="Home" />

      <section
        aria-label="Status"
        className="flex flex-col items-center gap-6 rounded-xl border bg-surface p-6 sm:flex-row sm:p-8"
      >
        <IrisRing alerts={s.alerts_by_status['new'] ?? 0} review={s.review_queue} />
        <div className="flex min-w-0 flex-1 flex-col gap-4 text-center sm:text-start">
          <div className="flex flex-col gap-1.5">
            <p className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</p>
            <p className="max-w-prose text-muted-foreground">{sub}</p>
          </div>
          <dl className="grid grid-cols-2 divide-x divide-y rounded-md border sm:grid-flow-col sm:auto-cols-fr sm:divide-y-0 rtl:divide-x-reverse">
            <Stat label="Messages today" value={s.messages_today} to="/messages" />
            <Stat label="Last 7 days" value={s.messages_7d} to="/messages" />
            <Stat label="In the queue" value={s.queue_depth} />
            <Stat label="Phones" value={s.instances} to="/instances" />
            {s.media_policy && s.media_policy !== 'off' && (
              <Stat
                label="Media kept"
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
            Needs attention
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
          Activity, last 14 days
        </h2>
        {timeline.isError ? (
          <QueryError what="the activity chart" onRetry={() => void timeline.refetch()} />
        ) : timeline.isLoading ? (
          <Skeleton className="h-52" />
        ) : days.length > 0 ? (
          <ActivityChart days={days} />
        ) : (
          <p className="py-8 text-center text-sm text-muted-foreground">
            The chart appears once Iris has seen some messages.
          </p>
        )}
      </section>

      <section aria-labelledby="recent" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 id="recent" className="text-lg font-semibold">
            Recent alerts
          </h2>
          <Link
            to="/alerts"
            className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-primary hover:bg-primary-soft"
          >
            See all
          </Link>
        </div>
        <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
          {alerts.data?.items.map((a) => (
            <AlertRow key={a.id} alert={a} />
          ))}
          {alerts.data && alerts.data.items.length === 0 && (
            <li>
              <EmptyState icon={BellRing} title="No alerts yet">
                When a message needs your attention, Iris lists it here and sends it to your
                WhatsApp.
              </EmptyState>
            </li>
          )}
        </ul>
      </section>
    </div>
  )
}
