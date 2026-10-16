import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, RotateCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { relativeTime } from '../lib/format'
import { strings, t } from '../lib/i18n'
import type { Job } from '../lib/types'
import { QueryError } from '../components/QueryError'

const WHAT: Record<string, string> = {
  process_message: strings.jobs.checkingMessage,
  deliver_alert: strings.jobs.sendingAlert,
  notify_change: strings.jobs.tellingChanged,
}

export function Jobs() {
  const qc = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<Job[]>('/api/jobs'),
    refetchInterval: 60_000,
  })
  const retry = useMutation({
    mutationFn: (id: number) => api(`/api/jobs/${id}/retry`, { method: 'POST' }),
    onSuccess: () => {
      toast.success(t('jobs.retrying'))
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t('jobs.retryFailed')),
  })
  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <PageHeader title={t('jobs.title')} description={t('jobs.description')} />
      {isLoading && <Skeleton className="h-32" />}
      {isError && <QueryError what={t('jobs.couldNotLoad')} onRetry={() => void refetch()} />}
      <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
        {data?.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
            <span className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{WHAT[j.type] ?? j.type}</span>
                <Badge tone="danger">
                  <CircleAlert />{' '}
                  {(strings.statuses as Record<string, string>)[j.status] ?? j.status}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {t('jobs.attemptOf', j.attempts, j.max_attempts)}, {relativeTime(j.created_at)}
                </span>
              </span>
              {j.last_error && (
                <span dir="auto" className="break-words text-sm text-danger">
                  {j.last_error}
                </span>
              )}
              {j.message_id && (
                <Link
                  to={`/messages/${j.message_id}`}
                  className="w-fit text-sm font-medium text-primary hover:underline"
                >
                  {t('jobs.seeMessage')}
                </Link>
              )}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={retry.isPending}
              onClick={() => retry.mutate(j.id)}
            >
              <RotateCw /> {t('jobs.retry')}
            </Button>
          </li>
        ))}
        {data?.length === 0 && (
          <li>
            <EmptyState icon={CheckCircle2} title={t('jobs.noneFailed')}>
              {t('jobs.noneFailedBody')}
            </EmptyState>
          </li>
        )}
      </ul>
    </div>
  )
}
