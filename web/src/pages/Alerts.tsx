import { useQuery } from '@tanstack/react-query'
import { BellRing, Settings } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertRow } from '../components/AlertRow'
import { EmptyState } from '../components/EmptyState'
import { Chips, FilterBar } from '../components/FilterBar'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { Button } from '../components/ui/button'
import { Field, Select } from '../components/ui/field'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { CATEGORIES } from '../lib/categories'
import type { AlertPage, Instance } from '../lib/types'

const STATUS = [
  { value: '', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'acknowledged', label: 'Seen' },
  { value: 'dismissed', label: 'Dismissed' },
]
const PAGE_SIZE = 25

export function Alerts() {
  const [sp, setSp] = useSearchParams()
  const status = sp.get('status') ?? ''
  const kid = sp.get('instance_id') ?? ''
  const category = sp.get('category') ?? ''
  const page = Number(sp.get('page') ?? '1')
  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('page' in changes)) next.delete('page')
    setSp(next, { replace: true })
  }

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  for (const [k, v] of [
    ['status', status],
    ['instance_id', kid],
    ['category', category],
  ])
    if (v) params.set(k, v)

  const { data: instances } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const { data, isLoading, isError } = useQuery({
    queryKey: ['alerts', params.toString()],
    queryFn: () => api<AlertPage>(`/api/alerts?${params}`),
  })
  const notConfigured = data?.items.some(
    (a) => a.delivery_error === 'alert delivery not configured',
  )
  const active = [kid, category].filter(Boolean).length + (status ? 1 : 0)

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Alerts" description="Messages Iris judged harmful, newest first." />

      {notConfigured && (
        <p
          role="status"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-warning-soft p-3 text-sm text-warning"
        >
          Alert delivery is not set up, so alerts are saved here but not sent to your WhatsApp.
          <Button asChild variant="link" size="sm" className="h-auto min-h-0 p-0">
            <Link to="/settings">
              <Settings /> Set up delivery
            </Link>
          </Button>
        </p>
      )}

      <FilterBar
        active={active}
        onClear={() => setSp(new URLSearchParams(), { replace: true })}
        leading={
          <Chips
            label="Status"
            value={status}
            options={STATUS}
            onChange={(v) => update({ status: v })}
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
            Could not load alerts. Reload the page; if it keeps failing, check the Jobs page and the
            server log.
          </li>
        )}
        {data?.items.map((a) => (
          <AlertRow key={a.id} alert={a} />
        ))}
        {data && data.items.length === 0 && (
          <li>
            {active > 0 ? (
              <EmptyState
                icon={BellRing}
                title="No alerts match these filters"
                action={
                  <Button
                    variant="outline"
                    onClick={() => setSp(new URLSearchParams(), { replace: true })}
                  >
                    Clear filters
                  </Button>
                }
              >
                Try a different status, phone or category.
              </EmptyState>
            ) : (
              <EmptyState icon={BellRing} title="No alerts yet">
                When a message needs your attention, Iris lists it here and sends it to your
                WhatsApp.
              </EmptyState>
            )}
          </li>
        )}
      </ul>
      {data && (
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
