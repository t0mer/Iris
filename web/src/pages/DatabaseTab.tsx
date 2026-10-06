import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Database, Loader2, PlugZap, Save, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { QueryError } from '../components/QueryError'
import { Section } from '../components/Section'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { ConfirmDialog } from '../components/ui/dialog'
import { Field, Input, Select } from '../components/ui/field'
import { Skeleton } from '../components/ui/skeleton'
import { Switch } from '../components/ui/switch'
import { api, ApiError } from '../lib/api'
import type { DatabaseProbe, DatabaseStatus, DbConfigInfo } from '../lib/types'

type Kind = DbConfigInfo['kind']
const LABEL: Record<Kind, string> = { sqlite: 'SQLite', postgresql: 'PostgreSQL', mysql: 'MySQL' }
const PORT: Record<Kind, string> = { sqlite: '', postgresql: '5432', mysql: '3306' }

interface Form {
  kind: Kind
  host: string
  port: string
  name: string
  user: string
  password: string
  tls: boolean
}

const fromSaved = (c: DbConfigInfo): Form => ({
  kind: c.kind,
  host: c.host,
  port: c.port ? String(c.port) : PORT[c.kind],
  name: c.name,
  user: c.user,
  password: '',
  tls: c.tls,
})

const describe = (c: DbConfigInfo) =>
  c.kind === 'sqlite' ? 'SQLite' : `${LABEL[c.kind]} on ${c.host}:${c.port}`

/** Settings > Database: pick SQLite, MySQL or PostgreSQL, try it, save it, and copy the data over. */
export function DatabaseTab() {
  const status = useQuery({
    queryKey: ['database'],
    queryFn: () => api<DatabaseStatus>('/api/database'),
    refetchInterval: (q) => (q.state.data?.copy_job.state === 'running' ? 1500 : false),
  })
  if (status.isError)
    return <QueryError what="the database settings" onRetry={() => void status.refetch()} />
  if (!status.data) return <Skeleton className="h-64" />
  // Remounting on a changed saved choice resets the form to what is stored.
  return <DatabaseForm key={JSON.stringify(status.data.saved)} data={status.data} />
}

function DatabaseForm({ data }: { data: DatabaseStatus }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<Form>(() => fromSaved(data.saved))
  const [probe, setProbe] = useState<DatabaseProbe | null>(null)

  const body = (f: Form) => ({
    kind: f.kind,
    host: f.host,
    port: f.port.trim() === '' ? null : Number(f.port),
    name: f.name,
    user: f.user,
    password: f.password || null,
    tls: f.tls,
  })

  const test = useMutation({
    mutationFn: (f: Form) =>
      api<DatabaseProbe>('/api/database/test', { method: 'POST', body: JSON.stringify(body(f)) }),
    onSuccess: setProbe,
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : 'Could not test the connection.'),
  })
  const save = useMutation({
    mutationFn: (f: Form) =>
      api<DatabaseStatus>('/api/database', { method: 'PUT', body: JSON.stringify(body(f)) }),
    onSuccess: (s) => {
      toast.success('Database choice saved.')
      qc.setQueryData(['database'], s)
      setProbe(null)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not save the database.'),
  })
  const reset = useMutation({
    mutationFn: () => api<DatabaseStatus>('/api/database', { method: 'DELETE' }),
    onSuccess: (s) => {
      toast.success('Iris will use SQLite again.')
      qc.setQueryData(['database'], s)
      setProbe(null)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not switch back.'),
  })
  const copy = useMutation({
    mutationFn: () => api('/api/database/copy', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['database'] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not start the copy.'),
  })

  if (status.isError)
    return <QueryError what="the database settings" onRetry={() => void status.refetch()} />
  if (!data || !form) return <Skeleton className="h-64" />

  const locked = data.env_override
  const set = (patch: Partial<Form>) => {
    setForm({ ...form, ...patch })
    setProbe(null)
  }
  const remote = form.kind !== 'sqlite'
  const job = data.copy_job
  const canCopy = data.restart_required && !locked && job.state !== 'running'

  return (
    <div className="flex flex-col gap-5">
      <Section
        title="Where Iris keeps its data"
        description="SQLite needs nothing to set up. Choose PostgreSQL or MySQL to keep the data on a database server."
      >
        <div className="flex flex-col gap-2 text-sm" role="status">
          <p>
            <span className="text-muted-foreground">Running on </span>
            <Badge tone="info">
              <Database /> {describe(data.running)}
            </Badge>
          </p>
          {data.restart_required && (
            <p>
              <span className="text-muted-foreground">Saved for the next start: </span>
              <Badge tone="warning">{describe(data.saved)}</Badge>
              <span className="mt-1 block text-muted-foreground">
                Restart Iris to start using it (for Docker: <code>docker restart iris</code>).
              </span>
            </p>
          )}
          {locked && (
            <p className="text-muted-foreground">
              The database is set by the <code>IRIS_DATABASE_URL</code> environment variable, so it
              cannot be changed here.
            </p>
          )}
        </div>
      </Section>

      <Section title="Database">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate(form)
          }}
        >
          <Field label="Type" className="max-w-64">
            <Select
              value={form.kind}
              disabled={locked}
              onChange={(e) => {
                const kind = e.target.value as Kind
                set({ kind, port: PORT[kind] })
              }}
            >
              <option value="sqlite">SQLite</option>
              <option value="mysql">MySQL</option>
              <option value="postgresql">PostgreSQL</option>
            </Select>
          </Field>

          {!remote && (
            <p className="max-w-prose text-sm text-muted-foreground">
              Iris stores everything in one file in its data folder. Messages are searched with the
              built-in full-text index.
            </p>
          )}

          {remote && (
            <>
              <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
                <Field label="Host">
                  <Input
                    dir="ltr"
                    value={form.host}
                    disabled={locked}
                    onChange={(e) => set({ host: e.target.value })}
                    autoComplete="off"
                  />
                </Field>
                <Field label="Port">
                  <Input
                    dir="ltr"
                    className="tabular"
                    type="number"
                    min={1}
                    max={65535}
                    value={form.port}
                    disabled={locked}
                    onChange={(e) => set({ port: e.target.value })}
                  />
                </Field>
              </div>
              <Field label="Database name" hint="Create it first and leave it empty.">
                <Input
                  dir="ltr"
                  value={form.name}
                  disabled={locked}
                  onChange={(e) => set({ name: e.target.value })}
                  autoComplete="off"
                />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="User">
                  <Input
                    dir="ltr"
                    value={form.user}
                    disabled={locked}
                    onChange={(e) => set({ user: e.target.value })}
                    autoComplete="off"
                  />
                </Field>
                <Field label="Password">
                  <Input
                    dir="ltr"
                    type="password"
                    value={form.password}
                    disabled={locked}
                    placeholder={data.saved.password_set ? 'Saved, leave blank to keep' : ''}
                    onChange={(e) => set({ password: e.target.value })}
                    autoComplete="new-password"
                  />
                </Field>
              </div>
              <label className="flex items-start justify-between gap-4 py-1 text-sm">
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium">Use TLS</span>
                  <span className="text-muted-foreground">
                    Encrypts the connection with the server&apos;s certificate.
                  </span>
                </span>
                <Switch
                  checked={form.tls}
                  disabled={locked}
                  onCheckedChange={(v) => set({ tls: v })}
                  aria-label="Use TLS"
                />
              </label>
              {form.kind === 'mysql' && (
                <p className="max-w-prose text-sm text-muted-foreground">
                  Create the database with the <code>utf8mb4</code> character set so Hebrew and
                  emoji are stored correctly.
                </p>
              )}
              <p className="max-w-prose text-sm text-muted-foreground">
                Search on {LABEL[form.kind]} finds a word anywhere inside a message, instead of the
                SQLite full-text index.
              </p>
            </>
          )}

          {probe && (
            <div
              role="status"
              className={`rounded-md p-3 text-sm ${probe.ok ? 'bg-success-soft' : 'bg-danger-soft text-danger'}`}
            >
              <p className="font-medium">{probe.ok ? probe.detail : probe.detail}</p>
              {probe.version && <p className="text-muted-foreground">Server {probe.version}</p>}
              {probe.warning && <p className="mt-1 text-warning">{probe.warning}</p>}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={locked || test.isPending}
              onClick={() => test.mutate(form)}
            >
              {test.isPending ? <Loader2 className="animate-spin" /> : <PlugZap />} Test connection
            </Button>
            <Button type="submit" disabled={locked || save.isPending}>
              <Save /> Save
            </Button>
            {!locked && data.saved.kind !== 'sqlite' && (
              <ConfirmDialog
                trigger={
                  <Button type="button" variant="ghost" disabled={reset.isPending}>
                    <Undo2 /> Use SQLite again
                  </Button>
                }
                title="Go back to SQLite?"
                description="Iris will use the SQLite file in its data folder after the next restart. Data in the other database stays where it is."
                confirmLabel="Use SQLite"
                tone="primary"
                onConfirm={() => reset.mutate()}
              />
            )}
          </div>
        </form>
      </Section>

      {(canCopy || job.state !== 'idle') && (
        <Section
          title="Move your data"
          description="Copy phones, settings, messages and alerts into the saved database. It must be empty. Your current database is not changed."
        >
          {job.state === 'idle' && (
            <ConfirmDialog
              trigger={
                <Button type="button" variant="outline" className="w-fit" disabled={!canCopy}>
                  <Copy /> Copy my data to {LABEL[data.saved.kind]}
                </Button>
              }
              title="Copy your data?"
              description="Messages that arrive while it copies are not included. Restart Iris right after it finishes."
              confirmLabel="Copy my data"
              tone="primary"
              onConfirm={() => copy.mutate()}
            />
          )}
          {job.state === 'running' && (
            <p role="status" className="flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" /> Copying {job.table || 'your data'}…
            </p>
          )}
          {job.state === 'done' && (
            <div role="status" className="text-sm">
              <p className="font-medium">Done. Restart Iris to start using the new database.</p>
              <ul className="mt-2 grid gap-x-6 text-muted-foreground sm:grid-cols-2">
                {Object.entries(job.copied)
                  .filter(([, n]) => n > 0)
                  .map(([t, n]) => (
                    <li key={t}>
                      <span className="tabular">{n}</span> {t.replace('_', ' ')}
                    </li>
                  ))}
              </ul>
            </div>
          )}
          {job.state === 'failed' && (
            <div role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
              {job.error}
              {canCopy && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="ms-3"
                  onClick={() => copy.mutate()}
                >
                  Try again
                </Button>
              )}
            </div>
          )}
        </Section>
      )}
    </div>
  )
}
