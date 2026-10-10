import { useMe } from '../lib/auth'
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellRing, Settings } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AlertRow } from '../components/AlertRow'
import { EmptyState } from '../components/EmptyState'
import { Chips, FilterBar } from '../components/FilterBar'
import { PageHeader } from '../components/PageHeader'
import { RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { Pagination } from '../components/Pagination'
import { Button } from '../components/ui/button'
import { Field, Select } from '../components/ui/field'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { CATEGORIES } from '../lib/categories'
import { useUrlState } from '../lib/urlState'
import type { AlertPage, Instance, Stats } from '../lib/types'

const STATUS = [
  { value: 'unseen', label: 'Unseen' },
  { value: 'seen', label: 'Seen' },
  { value: 'all', label: 'All' },
  { value: 'dismissed', label: 'Dismissed' },
]
const PAGE_SIZE = 25

export function Alerts() {
  const { data: me } = useMe()
  const qc = useQueryClient()
  const [visit, setVisit] = useState(0)
  const [snapshot, setSnapshot] = useState<{ key: string; data: AlertPage } | null>(null)
  const { revealed, toggle } = useReveal()
  const { get, page, update, clear } = useUrlState()
  const legacy = (
    { new: 'unseen', acknowledged: 'seen', dismissed: 'dismissed' } as Record<string, string>
  )[get('status')]
  const status = ['unseen', 'seen', 'all', 'dismissed'].includes(get('view'))
    ? get('view')
    : legacy || 'unseen'
  const kid = get('instance_id')
  const category = get('category')
  const chatId = get('chat_id')
  const media = get('media') === 'missing' ? 'missing' : ''

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  for (const [k, v] of [
    ['view', status],
    ['instance_id', kid],
    ['category', category],
    ['chat_id', chatId],
    ['media', media],
  ])
    if (v) params.set(k, v)

  const { data: instances } = useQuery({
    queryKey: ['auth-phones', me?.id],
    queryFn: () => api<Instance[]>('/api/auth/phones'),
  })
  const viewKey = `${me?.id}:${params.toString()}:${visit}`
  const frozen = snapshot?.key === viewKey
  const query = useQuery({
    queryKey: ['alerts', me?.id, params.toString(), visit],
    queryFn: () => api<AlertPage>(`/api/alerts?${params}`),
    enabled: !!me && !frozen,
    refetchOnWindowFocus: false,
  })
  const data = frozen ? snapshot.data : query.data
  const { isLoading, isError, refetch } = query
  const read = useMutation({
    mutationFn: ({ ids }: { ids: number[]; key: string }) =>
      api<{ marked: number; seen_at: string }>('/api/alerts/seen', {
        method: 'POST',
        body: JSON.stringify({ alert_ids: ids }),
      }),
    onSuccess: (result, { ids, key }) => {
      setSnapshot((previous) =>
        previous?.key === key
          ? {
              key,
              data: {
                ...previous.data,
                items: previous.data.items.map((a) =>
                  ids.includes(a.id) && a.status === 'new'
                    ? { ...a, status: 'acknowledged', seen_at: result.seen_at }
                    : a,
                ),
              },
            }
          : previous,
      )
      void qc.invalidateQueries({ queryKey: ['alerts'], refetchType: 'none' })
      void qc.invalidateQueries({ queryKey: ['alert'], refetchType: 'none' })
      void qc.invalidateQueries({ queryKey: ['stats'] })
    },
  })
  const markRead = read.mutate
  useEffect(() => {
    if (!me || frozen || !query.data || query.isFetching) return
    // Keep this visit's rows readable; disabling its query prevents read events
    // from fetching and marking subsequent unseen pages without user action.
    setSnapshot({ key: viewKey, data: query.data })
    const ids = query.data.items.filter((a) => a.status === 'new').map((a) => a.id)
    if (ids.length) markRead({ ids, key: viewKey })
  }, [me, frozen, query.data, query.isFetching, viewKey, markRead])
  const { data: stats } = useQuery({
    queryKey: ['stats', me?.id],
    queryFn: () => api<Stats>('/api/stats'),
  })
  const notConfigured = stats?.delivery_configured === false
  const active =
    [kid, category, chatId, media].filter(Boolean).length + (status !== 'unseen' ? 1 : 0)

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Alerts"
        description="Entering this page marks the displayed alerts read for your account. They remain visible during this visit and move to Seen when you return."
        actions={<RevealButton revealed={revealed} onToggle={toggle} />}
      />

      {read.isError && (
        <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
          Could not mark these alerts read.{' '}
          <button
            className="underline"
            onClick={() => {
              const ids = data?.items.filter((a) => a.status === 'new').map((a) => a.id) ?? []
              if (ids.length) read.mutate({ ids, key: viewKey })
            }}
          >
            Retry marking read
          </button>
        </p>
      )}
      {notConfigured && (
        <p
          role="status"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-warning-soft p-3 text-sm text-warning"
        >
          Alert delivery is not set up, so alerts are saved here but not sent to your WhatsApp.
          {me?.role === 'admin' && (
            <Button asChild variant="link" size="sm" className="h-auto min-h-0 p-0">
              <Link to="/settings?tab=Alerts">
                <Settings /> Set up delivery
              </Link>
            </Button>
          )}
        </p>
      )}

      {media === 'missing' && (
        <p role="status" className="rounded-lg border bg-surface-2 p-3 text-sm">
          Showing alerts with no saved media copy, including previously read alerts when All is
          selected. Open an alert to check whether its original is still available through OpenWA.
        </p>
      )}
      <FilterBar
        active={active}
        onClear={clear}
        leading={
          <Chips
            label="View"
            value={status}
            options={STATUS}
            onChange={(v) => update({ view: v, status: '' })}
          />
        }
      >
        <Field label="Phone" className="md:w-44">
          <Select value={kid} onChange={(e) => update({ instance_id: e.target.value })}>
            <option value="">All phones</option>
            {instances?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.kid_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Category" className="md:w-52">
          <Select value={category} onChange={(e) => update({ category: e.target.value })}>
            <option value="">Any category</option>
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </Field>
        <Field label="Media" className="md:w-52">
          <Select value={media} onChange={(e) => update({ media: e.target.value })}>
            <option value="">Any media status</option>
            <option value="missing">No saved media copy</option>
          </Select>
        </Field>
      </FilterBar>

      <ul className="divide-y overflow-hidden rounded-lg border bg-surface" aria-busy={isLoading}>
        {isLoading &&
          Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="p-4">
              <Skeleton className="h-16" />
            </li>
          ))}
        {isError && (
          <li className="p-4 text-sm text-danger" role="alert">
            Could not load alerts.{' '}
            <button className="underline" onClick={() => void refetch()}>
              Retry
            </button>
          </li>
        )}
        {data?.items.map((a) => (
          <AlertRow key={a.id} alert={a} revealed={revealed} />
        ))}
        {data && data.items.length === 0 && (
          <li>
            {active > 0 ? (
              <EmptyState
                icon={BellRing}
                title="No alerts match these filters"
                action={
                  <Button variant="outline" onClick={clear}>
                    Clear filters
                  </Button>
                }
              >
                Try a different status, phone or category.
              </EmptyState>
            ) : (
              <EmptyState icon={BellRing} title="No unseen alerts">
                You have no unread alerts. Choose Seen or All to revisit alerts you already opened.
              </EmptyState>
            )}
          </li>
        )}
      </ul>
      {data && status === 'unseen' && !read.isError && data.items.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {read.isPending
              ? 'Marking displayed alerts read…'
              : `${data.items.length} ${data.items.length === 1 ? 'alert' : 'alerts'} marked read for you`}
            {data.total > data.items.length
              ? ` · ${data.total - data.items.length} unread alerts remaining`
              : ''}
          </p>
          {data.total > data.items.length && (
            <Button
              variant="outline"
              disabled={read.isPending}
              onClick={() => {
                update({ page: '' })
                setVisit((value) => value + 1)
              }}
            >
              Next unread alerts
            </Button>
          )}
        </div>
      )}
      {data && status !== 'unseen' && (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={data.total}
          noun={['alert', 'alerts']}
          onPage={(p) => update({ page: String(p) })}
        />
      )}
    </div>
  )
}
