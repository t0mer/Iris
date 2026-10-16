import { useQuery } from '@tanstack/react-query'
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
import { categoryLabel, strings, t } from '../lib/i18n'
import { useUrlState } from '../lib/urlState'
import type { AlertPage, Instance } from '../lib/types'

const STATUS = [
  { value: '', label: strings.alerts.all },
  { value: 'new', label: strings.alerts.new },
  { value: 'acknowledged', label: strings.alerts.seen },
  { value: 'dismissed', label: strings.alerts.dismissed },
]
const PAGE_SIZE = 25

export function Alerts() {
  const { revealed, toggle } = useReveal()
  const { get, page, update, clear } = useUrlState()
  const status = get('status')
  const kid = get('instance_id')
  const category = get('category')

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
      <PageHeader
        title={t('alerts.title')}
        description={t('alerts.description')}
        actions={<RevealButton revealed={revealed} onToggle={toggle} />}
      />

      {notConfigured && (
        <p
          role="status"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-warning-soft p-3 text-sm text-warning"
        >
          {t('alerts.deliveryNotSetUp')}
          <Button asChild variant="link" size="sm" className="h-auto min-h-0 p-0">
            <Link to="/settings">
              <Settings /> {t('alerts.setUpDelivery')}
            </Link>
          </Button>
        </p>
      )}

      <FilterBar
        active={active}
        onClear={clear}
        leading={
          <Chips
            label={t('alerts.status')}
            value={status}
            options={STATUS}
            onChange={(v) => update({ status: v })}
          />
        }
      >
        <Field label={t('alerts.phone')} className="md:w-44">
          <Select value={kid} onChange={(e) => update({ instance_id: e.target.value })}>
            <option value="">{t('alerts.allPhones')}</option>
            {instances?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.kid_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('alerts.category')} className="md:w-52">
          <Select value={category} onChange={(e) => update({ category: e.target.value })}>
            <option value="">{t('alerts.anyCategory')}</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(c)}
              </option>
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
            {t('alerts.couldNotLoad')}
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
                title={t('alerts.noneMatch')}
                action={
                  <Button variant="outline" onClick={clear}>
                    {t('filterBar.clearFilters')}
                  </Button>
                }
              >
                {t('alerts.noneMatchBody')}
              </EmptyState>
            ) : (
              <EmptyState icon={BellRing} title={t('alerts.noneYet')}>
                {t('alerts.noneYetBody')}
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
          noun={strings.alerts.noun}
          onPage={(p) => update({ page: String(p) })}
        />
      )}
    </div>
  )
}
