import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import { Button } from '../components/ui/button'
import { ConfirmDialog } from '../components/ui/dialog'
import { Field, Input } from '../components/ui/field'
import { QueryError } from '../components/QueryError'

type Run = {
  id: number
  status: string
  started_at: string
  finished_at: string | null
  result: unknown
  error: string | null
  traceback: string | null
}
type Schedule = {
  retry_count?: number
  retry_wait_minutes?: number
  notify_wait_minutes?: number
  key: string
  name: string
  description: string
  enabled: boolean
  interval: number | null
  time: string
  next_run: string | null
  channel: string | null
  runs: Run[]
  recipients: {
    target: string
    name: string
    eligible: boolean
    reason: string | null
    children: string[]
  }[]
}
type Config = {
  enabled?: boolean
  interval?: number
  time?: string
  retry_count?: number
  retry_wait_minutes?: number
  notify_wait_minutes?: number
}

export function ScheduleSettings() {
  const qc = useQueryClient()
  const schedules = useQuery({
    queryKey: ['schedules'],
    queryFn: () =>
      api<{
        items: Schedule[]
        timezone: string
        workers_enabled: boolean
        history_policy: string
      }>('/api/schedules'),
    refetchInterval: 10_000,
  })
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
  const [view, setView] = useState('schedules')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(key: string, change: Config) {
    setBusy(true)
    setError('')
    try {
      const config = (settings.data?.['schedules.config'] as Record<string, Config>) || {}
      await api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          settings: { 'schedules.config': { ...config, [key]: { ...config[key], ...change } } },
        }),
      })
      await qc.invalidateQueries()
      toast.success('Schedule saved.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save schedule.')
    } finally {
      setBusy(false)
    }
  }
  async function run(key: string) {
    setBusy(true)
    setError('')
    try {
      const result = await api<{ job_ids: number[] }>(`/api/schedules/${key}/run`, {
        method: 'POST',
      })
      toast.success(
        result.job_ids.length
          ? 'Run queued. See run history or Jobs for the result.'
          : 'No active incidents to notify.',
      )
      await qc.invalidateQueries()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start schedule.')
    } finally {
      setBusy(false)
    }
  }
  if (schedules.isError)
    return <QueryError what="application schedules" onRetry={() => void schedules.refetch()} />
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Application schedules</h2>
      <p className="text-sm text-muted-foreground">
        Timezone: {schedules.data?.timezone}. {schedules.data?.history_policy}
      </p>
      {schedules.data && !schedules.data.workers_enabled && (
        <p role="alert" className="text-sm text-warning">
          Workers are paused. Queued and timed schedules wait until workers are enabled. Pairing
          cleanup continues independently.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant={view === 'schedules' ? 'primary' : 'outline'}
          onClick={() => setView('schedules')}
        >
          Schedules
        </Button>
        <Button
          variant={view === 'history' ? 'primary' : 'outline'}
          onClick={() => setView('history')}
        >
          Run history
        </Button>
      </div>
      {schedules.data?.items?.map((s) => (
        <article key={s.key} className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">{s.name}</h3>
            <span className={s.enabled ? 'text-sm text-success' : 'text-sm text-muted-foreground'}>
              {s.enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">{s.description}</p>
          {view === 'schedules' ? (
            <>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  aria-label={`Enable ${s.name}`}
                  checked={s.enabled}
                  disabled={busy}
                  onChange={(e) => void save(s.key, { enabled: e.target.checked })}
                />
                Enable schedule
              </label>
              {s.interval !== null && (
                <Field label={`Interval for ${s.name} (seconds)`}>
                  <Input
                    type="number"
                    min={15}
                    max={86400}
                    value={drafts[s.key] ?? s.interval}
                    onChange={(e) => setDrafts({ ...drafts, [s.key]: e.target.value })}
                  />
                  <Button
                    variant="outline"
                    disabled={busy || !drafts[s.key]}
                    onClick={() => void save(s.key, { interval: Number(drafts[s.key]) })}
                  >
                    Save interval
                  </Button>
                </Field>
              )}
              {s.key === 'connections' && (
                <div className="flex flex-col gap-3 rounded-lg border p-3">
                  <p className="text-sm text-muted-foreground">
                    One recovery cycle starts when a device goes offline and resets only after it is
                    online again. Set retry count to 0 to disable automatic refresh. Parent
                    notifications wait from the first offline detection; the dashboard updates
                    immediately.
                  </p>
                  {(
                    [
                      ['retry_count', 'Automatic refresh attempts', 0, 10, 1],
                      [
                        'retry_wait_minutes',
                        'Wait between refresh attempts (minutes)',
                        1,
                        1440,
                        10,
                      ],
                      [
                        'notify_wait_minutes',
                        'Wait before notifying parents (minutes)',
                        1,
                        1440,
                        10,
                      ],
                    ] as const
                  ).map(([field, label, min, max, fallback]) => (
                    <Field key={field} label={label}>
                      <Input
                        type="number"
                        min={min}
                        max={max}
                        value={drafts[`${s.key}.${field}`] ?? s[field] ?? fallback}
                        onChange={(e) =>
                          setDrafts({ ...drafts, [`${s.key}.${field}`]: e.target.value })
                        }
                      />
                      <Button
                        variant="outline"
                        className="max-w-full whitespace-normal"
                        disabled={busy || drafts[`${s.key}.${field}`] === undefined}
                        onClick={() => {
                          const value = Number(drafts[`${s.key}.${field}`])
                          if (
                            !drafts[`${s.key}.${field}`]?.trim() ||
                            !Number.isInteger(value) ||
                            value < min ||
                            value > max
                          ) {
                            setError(`${label}: enter a whole number from ${min} to ${max}.`)
                            return
                          }
                          void save(s.key, { [field]: value })
                        }}
                      >
                        Save {label.toLowerCase()}
                      </Button>
                    </Field>
                  ))}
                </div>
              )}
              {s.key === 'daily_summary' && (
                <Field label="Daily summary time">
                  <Input
                    type="time"
                    value={drafts[s.key] ?? s.time}
                    onChange={(e) => setDrafts({ ...drafts, [s.key]: e.target.value })}
                  />
                  <Button
                    variant="outline"
                    disabled={busy || !drafts[s.key]}
                    onClick={() => void save(s.key, { time: drafts[s.key] })}
                  >
                    Save time
                  </Button>
                </Field>
              )}
              {s.next_run && <p className="text-sm">Next due: {dateTime(s.next_run)}</p>}
              {s.channel && (
                <div className="text-sm">
                  <p>Delivery: {s.channel}</p>
                  <ul>
                    {s.recipients.map((r) => (
                      <li key={r.target} className={r.eligible ? '' : 'text-warning'}>
                        {r.name}:{' '}
                        {r.eligible
                          ? `Eligible · ${r.children?.join(', ') || 'No children'}`
                          : r.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <ConfirmDialog
                trigger={
                  <Button
                    variant="outline"
                    disabled={busy}
                    className="max-w-full whitespace-normal"
                  >
                    Run {s.name} now
                  </Button>
                }
                title={`Run ${s.name}?`}
                description={
                  s.channel
                    ? 'This sends a real notification to eligible selected recipients, respecting child assignments and sending limits.'
                    : s.key.includes('retention') || s.key.includes('cleanup')
                      ? 'This runs cleanup now and may permanently delete expired records or media according to the saved retention rules.'
                      : 'This queues the application task now. Its result is saved in run history.'
                }
                confirmLabel="Run now"
                tone="primary"
                onConfirm={() => run(s.key)}
              />
            </>
          ) : (
            <div className="flex flex-col gap-2">
              {!s.runs.length && (
                <p className="text-sm text-muted-foreground">No runs recorded yet.</p>
              )}
              {s.runs.map((r) => (
                <details key={r.id} className="rounded-md border p-3">
                  <summary className="cursor-pointer text-sm">
                    #{r.id} · {r.status} · {dateTime(r.started_at)}
                  </summary>
                  <div className="mt-2 flex flex-col gap-2 text-sm">
                    {r.finished_at && <p>Finished: {dateTime(r.finished_at)}</p>}
                    {r.result != null && (
                      <pre className="overflow-auto whitespace-pre-wrap">
                        {JSON.stringify(r.result, null, 2)}
                      </pre>
                    )}
                    {r.error && (
                      <p role="alert" className="text-danger">
                        {r.error}
                      </p>
                    )}
                    {r.traceback && (
                      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-surface-2 p-3">
                        {r.traceback}
                      </pre>
                    )}
                  </div>
                </details>
              ))}
            </div>
          )}
          {view === 'schedules' && s.runs[0]?.error && (
            <p className="text-sm text-danger">Last run: {s.runs[0].error}</p>
          )}
        </article>
      ))}
    </section>
  )
}
