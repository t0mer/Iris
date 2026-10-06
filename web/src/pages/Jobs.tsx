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
import type { Job } from '../lib/types'

const WHAT: Record<string, string> = {
  process_message: 'Checking a message',
  deliver_alert: 'Sending an alert',
}

export function Jobs() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<Job[]>('/api/jobs'),
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
        title="Jobs"
        description="Work that failed or ran out of attempts. Fix the cause shown, then try again."
      />
      {isLoading && <Skeleton className="h-32" />}
      <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
        {data?.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
            <span className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{WHAT[j.type] ?? j.type}</span>
                <Badge tone="danger">
                  <CircleAlert /> {j.status}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  attempt {j.attempts} of {j.max_attempts}, {relativeTime(j.created_at)}
                </span>
              </span>
              {j.last_error && (
                <span className="break-words text-sm text-danger">{j.last_error}</span>
              )}
              {j.message_id && (
                <Link
                  to={`/messages/${j.message_id}`}
                  className="w-fit text-sm font-medium text-primary hover:underline"
                >
                  See the message
                </Link>
              )}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={retry.isPending}
              onClick={() => retry.mutate(j.id)}
            >
              <RotateCw /> Retry
            </Button>
          </li>
        ))}
        {data?.length === 0 && (
          <li>
            <EmptyState icon={CheckCircle2} title="No failed jobs">
              If a message cannot be checked or an alert cannot be sent, it appears here with the
              reason.
            </EmptyState>
          </li>
        )}
      </ul>
    </div>
  )
}
