import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { SkippedGroups } from '../components/SkippedGroups'
import { Smartphone } from 'lucide-react'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/ui/skeleton'
import { QueryError } from '../components/QueryError'
import { AddPhone, PhoneCard } from '../components/PhoneConnections'
import { api } from '../lib/api'
import type { Instance } from '../lib/types'

export function Instances() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
    refetchInterval: 10_000,
  })
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
  const senderId = Number(settings?.['alerts.sender_instance_id'])
  const children = data?.filter((phone) => phone.role !== 'parent' && phone.id !== senderId)
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="Phones"
        description="Manage monitored children. Parent recipients and sender connections are in Settings → Alerts."
      />
      <Link to="/setup" className="text-sm text-primary underline">
        Return to setup checklist
      </Link>
      {isLoading && <Skeleton className="h-48" />}
      {isError && <QueryError what="your phones" onRetry={() => void refetch()} />}
      <h2 className="text-lg font-semibold">Children</h2>
      <AddPhone defaultRole="child" />
      <SkippedGroups />
      <ul className="flex flex-col gap-4">
        {children?.map((phone) => (
          <PhoneCard key={phone.id} i={phone} />
        ))}
      </ul>
      {children?.length === 0 && (
        <div className="rounded-lg border bg-surface">
          <EmptyState icon={Smartphone} title="No phones yet">
            Add the first child's number to start watching. You will need an OpenWA session for it.
          </EmptyState>
        </div>
      )}
    </div>
  )
}
