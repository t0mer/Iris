import { t } from '../lib/i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, RotateCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from '../lib/notify'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { Job } from '../lib/types'
import { QueryError } from '../components/QueryError'
import { useUrlState } from '../lib/urlState'
import { Field, Select } from '../components/ui/field'

const WHAT: Record<string, string> = {
  process_message: 'Checking a message',
  deliver_alert: 'Sending an alert',
  notify_change: 'Telling you a message changed',
  test_alert: 'Sending a test alert',
}

export function Jobs() {
  const qc = useQueryClient()
  const { get, update } = useUrlState()
  const status = get('status')
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['jobs', status],
    queryFn: () => api<Job[]>(`/api/jobs${status ? '?status=' + encodeURIComponent(status) : ''}`),
    refetchInterval: 60_000,
  })
  const retry = useMutation({
    mutationFn: (id: number) => api(`/api/jobs/${id}/retry`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Trying again.')
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not retry the job.'),
  })
  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <PageHeader
        title={t('Jobs')}
        description={t(
          'Track queued work and delivery results. Failed jobs can be retried after checking the cause.',
        )}
      />
      <Field label={t('Job status')}>
        <Select value={status} onChange={(e) => update({ status: e.target.value })}>
          <option value="">{t('Needs attention')}</option>
          <option value="queued">{t('Queued')}</option>
          <option value="running">{t('Running')}</option>
          <option value="done">{t('Completed')}</option>
        </Select>
      </Field>
      {isLoading && <Skeleton className="h-32" />}
      {isError && <QueryError what="the jobs" onRetry={() => void refetch()} />}
      <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
        {data?.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
            <span className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{t(WHAT[j.type] ?? j.type)}</span>
                <Badge
                  tone={
                    j.status === 'done'
                      ? 'success'
                      : ['failed', 'dead'].includes(j.status)
                        ? 'danger'
                        : 'warning'
                  }
                >
                  <CircleAlert /> {j.status}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {t('attempt')} {j.attempts} {t('of')} {j.max_attempts},{' '}
                  {relativeTime(j.created_at)}
                </span>
              </span>
              {j.last_error && (
                <span
                  className={
                    j.status === 'queued'
                      ? 'break-words text-sm text-muted-foreground'
                      : 'break-words text-sm text-danger'
                  }
                >
                  {j.last_error}
                </span>
              )}
              {j.status === 'queued' && j.run_after && (
                <span className="text-xs text-muted-foreground">
                  {t('Next attempt:')} {new Date(j.run_after).toLocaleString()}
                </span>
              )}
              {j.message_id && (
                <Link
                  to={`/messages/${j.message_id}`}
                  className="w-fit text-sm font-medium text-primary hover:underline"
                >
                  {t('See the message')}
                </Link>
              )}
            </span>
            {['failed', 'dead'].includes(j.status) && (
              <Button
                variant="outline"
                size="sm"
                disabled={retry.isPending}
                onClick={() => retry.mutate(j.id)}
              >
                <RotateCw /> {t('Retry')}
              </Button>
            )}
          </li>
        ))}
        {data?.length === 0 && (
          <li>
            <EmptyState
              icon={CheckCircle2}
              title={
                status === 'queued'
                  ? t('No queued jobs')
                  : status === 'running'
                    ? t('No running jobs')
                    : status === 'done'
                      ? t('No completed jobs')
                      : t('No failed jobs')
              }
            >
              {t(
                'If a message cannot be checked or an alert cannot be sent, it appears here with the reason.',
              )}
            </EmptyState>
          </li>
        )}
      </ul>
    </div>
  )
}
