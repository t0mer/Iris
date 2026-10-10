import { useMe } from '../lib/auth'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  BellRing,
  ChevronDown,
  ListChecks,
  ServerCrash,
  Settings,
  Smartphone,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { DashboardMetrics } from '../components/DashboardMetrics'
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
import type { AlertPage, Stats, Timeline, Instance, Chat } from '../lib/types'
import { QueryError } from '../components/QueryError'
import { SetupReminders } from '../components/SetupReminders'

const REFRESH_MS = 60_000

function HomeSection({
  id,
  title,
  children,
  className = 'rounded-lg border bg-surface p-4 sm:p-5',
}: {
  id: string
  title: string
  children: ReactNode
  className?: string
}) {
  const [expanded, setExpanded] = useState(id === 'activity')
  return (
    <section aria-labelledby={`${id}-heading`} className={className}>
      <h2 id={`${id}-heading`} className="text-lg font-semibold">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={`${id}-content`}
          onClick={() => setExpanded((value) => !value)}
          className="flex min-h-11 w-full items-center justify-between gap-3 rounded-md text-start focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600"
        >
          {title}
          <ChevronDown
            aria-hidden="true"
            className={`size-5 shrink-0 transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
      </h2>
      <div id={`${id}-content`} hidden={!expanded}>
        <div className="mt-3 flex flex-col gap-3">{children}</div>
      </div>
    </section>
  )
}

interface Item {
  icon: LucideIcon
  to: string
  action: string
  text: ReactNode
  tone: 'danger' | 'warning'
}

function attentionItems(s: Stats): Item[] {
  const items: Item[] = []
  for (const incident of s.monitoring_issues ?? [])
    items.push({
      icon: ServerCrash,
      to: '/instances',
      action: 'Repair monitoring',
      tone: 'danger',
      text: `${incident.kid_name}: ${incident.issues.join('; ')}${incident.notify_after ? ` · Auto refresh ${incident.refresh_attempts ?? 0}/${incident.refresh_limit ?? 1}; parent alert after ${new Date(incident.notify_after).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}${incident.refresh_error ? ` · ${incident.refresh_error}` : ''}`,
    })
  for (const failure of s.schedule_failures ?? [])
    items.push({
      icon: Activity,
      to: '/settings?tab=Schedules',
      action: 'View failed run',
      tone: 'warning',
      text: `${failure.key}: ${failure.error}`,
    })
  for (const issue of s.alert_delivery_issues ?? [])
    items.push({
      icon: Settings,
      to: '/settings?tab=Notifications',
      action: 'Fix alert delivery',
      tone: 'warning',
      text: issue,
    })
  if ((s.children ?? s.instances) === 0)
    items.push({
      icon: Smartphone,
      to: '/instances',
      action: 'Add a child',
      tone: 'warning',
      text: 'No child phone is configured. Iris cannot monitor children yet.',
    })
  if (s.parent_recipients === 0)
    items.push({
      icon: Settings,
      to: '/settings?tab=Alerts',
      action: 'Add parents',
      tone: 'warning',
      text: 'No parent recipients are configured. Select parents and add destinations for your alert channel.',
    })
  if (s.alert_sender_configured === false && (!s.alert_channel || s.alert_channel === 'openwa'))
    items.push({
      icon: Smartphone,
      to: '/settings?tab=Alerts',
      action: 'Set alert phone',
      tone: 'warning',
      text: 'No alert phone is set. Connect a sender phone and select it to send alerts to parents.',
    })
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
      to: '/settings?tab=Alerts',
      action: 'Set up delivery',
      tone: 'warning',
      text: 'Alert delivery is not configured, so alerts are recorded but not sent.',
    })
  const undelivered = s.alerts_by_delivery['failed'] ?? 0
  if ((s.unavailable_instances ?? 0) > 0)
    items.push({
      icon: ServerCrash,
      to: '/instances',
      action: 'Check sessions',
      tone: 'danger',
      text: 'A monitored phone or the alert sender is disconnected or unreachable. Monitoring or delivery may have stopped.',
    })
  if (s.sender_is_recipient)
    items.push({
      icon: Smartphone,
      to: '/settings?tab=Alerts',
      action: 'Check recipients',
      tone: 'warning',
      text: 'The sender is also a parent recipient. Messages to yourself may not notify you; use a separate sender phone for reliable parent notifications.',
    })
  if ((s.alerts_by_delivery['partial'] ?? 0) > 0)
    items.push({
      icon: BellRing,
      to: '/alerts',
      action: 'Check delivery',
      tone: 'warning',
      text: 'Some alerts reached only part of the parent recipient list.',
    })
  if (s.delivery_configured && undelivered > 0)
    items.push({
      icon: ServerCrash,
      to: '/alerts',
      action: 'See alerts',
      tone: 'danger',
      text: `${undelivered} ${plural(undelivered, 'alert was', 'alerts were')} not delivered through the selected alert channel`,
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
      text: `${s.silent_instances} ${plural(s.silent_instances, 'phone has', 'phones have')} never received a webhook. This may be normal until a message arrives.`,
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
    return {
      title: 'Needs attention',
      sub: 'Monitoring or alert delivery needs setting up or fixing, below.',
    }
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
  const queryClient = useQueryClient()
  const { data: me } = useMe()
  const watch = me?.role !== 'admin'
  const { revealed, toggle } = useReveal()
  const [activityDays, setActivityDays] = useState(14)
  const [childId, setChildId] = useState('')
  const children = useQuery({
    queryKey: ['auth-phones', me?.id],
    queryFn: () => api<Instance[]>('/api/auth/phones'),
  })
  const chats = useQuery({
    queryKey: ['chats'],
    queryFn: () => api<Chat[]>('/api/chats'),
    refetchInterval: REFRESH_MS,
  })
  const stats = useQuery({
    queryKey: ['stats', me?.id],
    queryFn: () => api<Stats>('/api/stats'),
    refetchInterval: REFRESH_MS,
  })
  const storage = useQuery({
    queryKey: ['storage'],
    queryFn: () =>
      api<{
        iris: { bytes: number | null; database_bytes: number | null; status: string }
        openwa: { bytes: number | null; database_bytes: number | null; status: string }
        disk?: {
          total_bytes: number | null
          used_bytes: number | null
          free_bytes: number | null
          status: string
        }
        resources?: {
          memory: {
            used_bytes: number | null
            total_bytes: number | null
            free_bytes: number | null
          }
          cpu: { usage_percentage: number | null; cores: number | null; sample_seconds: number }
        }
        iris_media_bytes: number
      }>('/api/stats/storage'),
    enabled: me?.role === 'admin',
    refetchInterval: REFRESH_MS,
  })
  const timeline = useQuery({
    queryKey: ['timeline', activityDays, childId],
    queryFn: () =>
      api<Timeline>(
        `/api/stats/timeline?days=${activityDays}${childId ? `&instance_id=${childId}` : ''}`,
      ),
    refetchInterval: REFRESH_MS,
  })
  const alerts = useQuery({
    queryKey: ['alerts', me?.id, 'recent'],
    queryFn: () => api<AlertPage>('/api/alerts?page_size=5'),
    refetchInterval: REFRESH_MS,
  })
  const dismissMediaWarning = useMutation({
    mutationFn: (throughAlertId: number) =>
      api('/api/stats/media-warning/dismiss', {
        method: 'POST',
        body: JSON.stringify({ through_alert_id: throughAlertId }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['stats', me?.id] }),
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
  const items = attentionItems(s).filter(
    (item) =>
      !watch || !['/settings', '/jobs', '/instances'].some((path) => item.to?.startsWith(path)),
  )
  const { title, sub } = headline(s, items)
  const days = timeline.data?.days ?? []

  return (
    <div className="flex flex-col gap-8">
      <PageHeader title="Home" />
      {me?.role === 'admin' && <SetupReminders userId={me.id} />}

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
          <dl className="grid grid-cols-2 divide-x divide-y rounded-md border sm:grid-cols-3 rtl:divide-x-reverse">
            <Stat label="Messages today" value={s.messages_today} to="/messages" />
            <Stat label="Last 7 days" value={s.messages_7d} to="/messages" />
            <Stat label="In the queue" value={s.queue_depth} />
            <Stat
              label="Children"
              value={s.children ?? s.instances}
              to={watch ? undefined : '/instances'}
            />
            <Stat
              label="Parents"
              value={s.parent_recipients ?? 0}
              to={watch ? undefined : '/settings?tab=Alerts'}
              note="Alert recipients"
            />
            <Stat
              label="Alert phones"
              value={s.alert_phones ?? 0}
              to={watch ? undefined : '/settings?tab=Alerts'}
              note="Sender connections"
            />
            {((s.media_policy && s.media_policy !== 'off') || (s.media_files ?? 0) > 0) && (
              <Stat
                label="Media kept"
                value={s.media_files ?? 0}
                note={fileSize(s.media_bytes ?? 0)}
              />
            )}
          </dl>
        </div>
      </section>

      {(s.alert_media_warning_count ?? s.alert_media_not_saved ?? 0) > 0 && (
        <section
          className="rounded-lg border bg-warning-soft p-4"
          aria-label="Alert media not saved"
        >
          <h2 className="font-semibold">
            {s.alert_media_warning_count ?? s.alert_media_not_saved} alerts have no saved media copy
          </h2>
          <p className="mt-1 text-sm">
            Photos or recordings may be missing in Messages. Keep media may be off, the content may
            be unexamined, or its copy may have expired. The original can be checked through OpenWA
            when available.
          </p>
          <Link className="mt-2 inline-block text-primary" to="/alerts?view=all&media=missing">
            View affected alerts
          </Link>
          <button
            type="button"
            disabled={dismissMediaWarning.isPending}
            onClick={() => dismissMediaWarning.mutate(s.alert_media_warning_latest_id ?? 0)}
            className="ms-3 mt-2 inline-flex min-h-10 items-center rounded-md border px-3 text-sm font-medium hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600 disabled:opacity-50"
          >
            {dismissMediaWarning.isPending ? 'Dismissing…' : 'Dismiss warning'}
          </button>
          {dismissMediaWarning.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              Could not dismiss the warning. Please try again.
            </p>
          )}
        </section>
      )}
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

      <HomeSection id="activity" title={`Activity, last ${activityDays} days`}>
        <div className="flex flex-wrap gap-3">
          <label className="text-sm">
            Time period
            <select
              className="ml-2 rounded border bg-surface p-2"
              aria-label="Activity time period"
              value={activityDays}
              onChange={(e) => setActivityDays(Number(e.target.value))}
            >
              {[1, 7, 14, 30, 60, 90].map((n) => (
                <option key={n} value={n}>
                  {n} days
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Child
            <select
              className="ml-2 rounded border bg-surface p-2"
              aria-label="Activity child"
              value={childId}
              onChange={(e) => setChildId(e.target.value)}
            >
              <option value="">All children</option>
              {children.data
                ?.filter((c) => c.role !== 'parent')
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.kid_name}
                  </option>
                ))}
            </select>
          </label>
        </div>
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
      </HomeSection>

      <HomeSection id="group-alerts" title="Alerts per group / contact">
        <p className="text-sm text-muted-foreground">
          All retained alerts, with the children linked to each conversation.
        </p>
        {chats.isError ? (
          <QueryError what="chat alert counts" onRetry={() => void chats.refetch()} />
        ) : (
          <ul className="divide-y">
            {chats.data
              ?.filter(
                (c) =>
                  c.alert_count > 0 && (!childId || c.kids.some((k) => k.id === Number(childId))),
              )
              .sort((a, b) => b.alert_count - a.alert_count)
              .map((c) => (
                <li key={c.id} className="flex justify-between gap-3 py-3">
                  <Link
                    to={`/alerts?chat_id=${c.id}${childId ? `&instance_id=${childId}` : ''}`}
                    className="text-primary"
                  >
                    {c.name || (c.is_group ? 'Unnamed group' : 'Direct contact')}
                    <span className="block text-sm text-muted-foreground">
                      {c.is_group ? 'Group' : 'Contact'} ·{' '}
                      {c.kids.map((k) => k.kid_name).join(', ') || 'No child linked'}
                    </span>
                  </Link>
                  <span>{c.alert_count} alerts</span>
                </li>
              ))}
          </ul>
        )}
      </HomeSection>

      <HomeSection id="recent" title="Recent alerts">
        <div className="flex items-center justify-end">
          <div className="flex items-center gap-1">
            <RevealButton revealed={revealed} onToggle={toggle} />
            <Link
              to="/alerts"
              className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-primary hover:bg-primary-soft"
            >
              See all
            </Link>
          </div>
        </div>
        <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
          {alerts.isError && (
            <li className="p-4">
              <QueryError what="recent alerts" onRetry={() => void alerts.refetch()} />
            </li>
          )}
          {alerts.data?.items.map((a) => (
            <AlertRow key={a.id} alert={a} revealed={revealed} />
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
      </HomeSection>
      {me?.role === 'admin' && (
        <HomeSection
          id="resources"
          title="System resources"
          className="rounded-3xl border border-purple-200 bg-white p-5 text-purple-950 sm:p-6 dark:border-purple-800/70 dark:bg-[#18142b] dark:text-purple-50"
        >
          <p className="text-sm text-purple-700 dark:text-purple-300">
            CPU, memory, disk usage and the data Iris keeps.
          </p>
          {storage.isError ? (
            <QueryError what="storage usage" onRetry={() => void storage.refetch()} />
          ) : !storage.data ? (
            <Skeleton className="h-16" />
          ) : (
            <>
              <DashboardMetrics
                disk={{
                  percentage:
                    storage.data.disk?.total_bytes && storage.data.disk.used_bytes !== null
                      ? (storage.data.disk.used_bytes / storage.data.disk.total_bytes) * 100
                      : null,
                  usedBytes: storage.data.disk?.used_bytes ?? null,
                  totalBytes: storage.data.disk?.total_bytes ?? null,
                  freeBytes: storage.data.disk?.free_bytes ?? null,
                }}
                memory={{
                  percentage:
                    storage.data.resources?.memory.total_bytes &&
                    storage.data.resources.memory.used_bytes !== null
                      ? (storage.data.resources.memory.used_bytes /
                          storage.data.resources.memory.total_bytes) *
                        100
                      : null,
                  usedBytes: storage.data.resources?.memory.used_bytes ?? null,
                  totalBytes: storage.data.resources?.memory.total_bytes ?? null,
                  freeBytes: storage.data.resources?.memory.free_bytes ?? null,
                }}
                cpu={{
                  percentage: storage.data.resources?.cpu.usage_percentage ?? null,
                  cores: storage.data.resources?.cpu.cores ?? null,
                }}
              />
              <div>
                <dl className="col-span-full grid gap-3 sm:grid-cols-3">
                  {(['iris', 'openwa'] as const).map((source) => (
                    <div
                      key={source}
                      className="rounded-2xl border border-purple-100 bg-purple-50/60 p-5"
                    >
                      <dt className="font-medium">{source === 'iris' ? 'Iris' : 'OpenWA'} data</dt>
                      <dd>
                        {storage.data[source].bytes === null
                          ? storage.data[source].status
                          : fileSize(storage.data[source].bytes)}
                        <span className="mt-2 block text-xs text-purple-700 dark:text-purple-300">
                          Database files on this volume:{' '}
                          {storage.data[source].database_bytes === null
                            ? 'Unavailable'
                            : fileSize(storage.data[source].database_bytes)}
                        </span>
                      </dd>
                    </div>
                  ))}
                  <div className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5">
                    <dt className="text-sm font-medium text-indigo-900">Iris kept media</dt>
                    <dd className="mt-1 text-xl font-semibold text-indigo-700">
                      {fileSize(storage.data.iris_media_bytes)}
                    </dd>
                    <dd className="mt-1 text-xs text-indigo-700">Includes remote storage</dd>
                  </div>
                </dl>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-purple-700 dark:text-purple-300">
                Measured file sizes, refreshed each minute. Database size includes indexes and free
                pages; it is not a text-only size. Iris retention controls Iris copies. OpenWA keeps
                its own database, sessions and cache; configure its retention separately.
              </p>
              <p className="mt-3 text-xs leading-relaxed text-purple-700 dark:text-purple-300">
                Keep media is{' '}
                {s.media_policy === 'off'
                  ? 'off: Iris does not save new media copies'
                  : 'enabled for the selected verdicts'}
                . Unexamined and withheld media are not saved. Opening an original from OpenWA does
                not retain an Iris copy.
              </p>
              <Link
                className="me-3 mt-4 inline-flex min-h-10 items-center rounded-xl border border-purple-200 bg-purple-50 px-4 text-sm font-medium text-purple-800 hover:bg-purple-100 dark:border-purple-700 dark:bg-purple-900/40 dark:text-purple-200 dark:hover:bg-purple-800/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600"
                to="/settings?tab=Media"
              >
                Configure Keep media
              </Link>
              <Link
                className="me-3 mt-4 inline-flex min-h-10 items-center rounded-xl border border-purple-200 bg-purple-50 px-4 text-sm font-medium text-purple-800 hover:bg-purple-100 dark:border-purple-700 dark:bg-purple-900/40 dark:text-purple-200 dark:hover:bg-purple-800/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600"
                to="/settings?tab=Retention"
              >
                Manage Iris retention
              </Link>
            </>
          )}
        </HomeSection>
      )}
    </div>
  )
}
