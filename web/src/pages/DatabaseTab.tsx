import { he } from '../lib/he'
import { apiErrorMessage } from '../lib/apiErrors'
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
import { t } from '../lib/i18n'
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
    return <QueryError what={t('databaseTab.couldNotLoad')} onRetry={() => void status.refetch()} />
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
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t('databaseTab.testFailed')),
  })
  const save = useMutation({
    mutationFn: (f: Form) =>
      api<DatabaseStatus>('/api/database', { method: 'PUT', body: JSON.stringify(body(f)) }),
    onSuccess: (s) => {
      toast.success(t('databaseTab.saved'))
      qc.setQueryData(['database'], s)
      setProbe(null)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t('databaseTab.saveFailed')),
  })
  const reset = useMutation({
    mutationFn: () => api<DatabaseStatus>('/api/database', { method: 'DELETE' }),
    onSuccess: (s) => {
      toast.success(t('databaseTab.reset'))
      qc.setQueryData(['database'], s)
      setProbe(null)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t('databaseTab.resetFailed')),
  })
  const copy = useMutation({
    mutationFn: () => api('/api/database/copy', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['database'] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t('databaseTab.copyFailed')),
  })

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
      <Section title={t('databaseTab.whereTitle')} description={t('databaseTab.whereDesc')}>
        <div className="flex flex-col gap-2 text-sm" role="status">
          <p>
            <span className="text-muted-foreground">{t('databaseTab.runningOn')}</span>
            <Badge tone="info">
              <Database /> <span dir="ltr">{describe(data.running)}</span>
            </Badge>
          </p>
          {data.restart_required && (
            <p>
              <span className="text-muted-foreground">{t('databaseTab.savedForNextStart')}</span>
              <Badge tone="warning">
                <span dir="ltr">{describe(data.saved)}</span>
              </Badge>
              <span className="mt-1 block text-muted-foreground">
                {t('databaseTab.restartToUse')}
              </span>
            </p>
          )}
          {data.config_error && (
            <p role="alert" className="rounded-md bg-danger-soft p-3 text-danger">
              {apiErrorMessage(data.config_error, 500)}
            </p>
          )}
          {locked && <p className="text-muted-foreground">{t('databaseTab.envLocked')}</p>}
        </div>
      </Section>

      <Section title={t('databaseTab.sectionTitle')}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate(form)
          }}
        >
          <Field label={t('databaseTab.type')} className="max-w-64">
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
              {t('databaseTab.sqliteDesc')}
            </p>
          )}

          {remote && (
            <>
              <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
                <Field label={t('databaseTab.host')}>
                  <Input
                    dir="ltr"
                    value={form.host}
                    disabled={locked}
                    onChange={(e) => set({ host: e.target.value })}
                    autoComplete="off"
                  />
                </Field>
                <Field label={t('databaseTab.port')}>
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
              <Field label={t('databaseTab.dbName')} hint={t('databaseTab.dbNameHint')}>
                <Input
                  dir="ltr"
                  value={form.name}
                  disabled={locked}
                  onChange={(e) => set({ name: e.target.value })}
                  autoComplete="off"
                />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t('databaseTab.user')}>
                  <Input
                    dir="ltr"
                    value={form.user}
                    disabled={locked}
                    onChange={(e) => set({ user: e.target.value })}
                    autoComplete="off"
                  />
                </Field>
                <Field
                  label={t('databaseTab.password')}
                  hint={data.saved.password_set ? t('databaseTab.passwordHint') : undefined}
                >
                  <Input
                    dir="ltr"
                    type="password"
                    value={form.password}
                    disabled={locked}
                    placeholder={
                      data.saved.password_set ? t('databaseTab.passwordPlaceholder') : ''
                    }
                    onChange={(e) => set({ password: e.target.value })}
                    autoComplete="new-password"
                  />
                </Field>
              </div>
              <label className="flex items-start justify-between gap-4 py-1 text-sm">
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium">{t('databaseTab.useTls')}</span>
                  <span className="text-muted-foreground">{t('databaseTab.useTlsHint')}</span>
                </span>
                <Switch
                  checked={form.tls}
                  disabled={locked}
                  onCheckedChange={(v) => set({ tls: v })}
                  aria-label={t('databaseTab.useTls')}
                />
              </label>
              {form.kind === 'mysql' && (
                <p className="max-w-prose text-sm text-muted-foreground">
                  {t('databaseTab.mysqlCharset')}
                </p>
              )}
              <p className="max-w-prose text-sm text-muted-foreground">
                {t('databaseTab.searchNote', LABEL[form.kind])}
              </p>
            </>
          )}

          {probe && (
            <div
              role={probe.ok ? 'status' : 'alert'}
              className={`rounded-md p-3 text-sm ${probe.ok ? 'bg-success-soft' : 'bg-danger-soft text-danger'}`}
            >
              <p className="font-medium">{apiErrorMessage(probe.detail, probe.ok ? 200 : 400)}</p>
              {probe.version && (
                <p className="text-muted-foreground">
                  {t('databaseTab.serverVersion')} <span dir="ltr">{probe.version}</span>
                </p>
              )}
              {probe.warning && (
                <p className="mt-1 text-warning">{apiErrorMessage(probe.warning, 400)}</p>
              )}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={locked || test.isPending}
              onClick={() => test.mutate(form)}
            >
              {test.isPending ? <Loader2 className="animate-spin" /> : <PlugZap />}{' '}
              {t('databaseTab.testConnection')}
            </Button>
            <Button type="submit" disabled={locked || save.isPending}>
              <Save /> {t('common.save')}
            </Button>
            {!locked && data.saved.kind !== 'sqlite' && (
              <ConfirmDialog
                trigger={
                  <Button type="button" variant="ghost" disabled={reset.isPending}>
                    <Undo2 /> {t('databaseTab.useSqliteAgain')}
                  </Button>
                }
                title={t('databaseTab.backToSqliteTitle')}
                description={t('databaseTab.backToSqliteDesc')}
                confirmLabel={t('databaseTab.useSqliteConfirm')}
                tone="primary"
                onConfirm={() => reset.mutate()}
              />
            )}
          </div>
        </form>
      </Section>

      {(canCopy || job.state !== 'idle') && (
        <Section title={t('databaseTab.moveTitle')} description={t('databaseTab.moveDesc')}>
          {job.state === 'idle' && (
            <ConfirmDialog
              trigger={
                <Button type="button" variant="outline" className="w-fit" disabled={!canCopy}>
                  <Copy /> {t('databaseTab.copyDataTo', LABEL[data.saved.kind])}
                </Button>
              }
              title={t('databaseTab.copyTitle')}
              description={t('databaseTab.copyDesc')}
              confirmLabel={t('databaseTab.copyConfirm')}
              tone="primary"
              onConfirm={() => copy.mutate()}
            />
          )}
          {job.state === 'running' && (
            <p role="status" className="flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" />{' '}
              {t('databaseTab.copying', tableLabel(job.table) || t('databaseTab.yourData'))}
            </p>
          )}
          {job.state === 'done' && (
            <div role="status" className="text-sm">
              <p className="font-medium">{t('databaseTab.done')}</p>
              <ul className="mt-2 grid gap-x-6 text-muted-foreground sm:grid-cols-2">
                {Object.entries(job.copied)
                  .filter(([, n]) => n > 0)
                  .map(([table, n]) => (
                    <li key={table}>
                      <span className="tabular">{n}</span> {tableLabel(table)}
                    </li>
                  ))}
              </ul>
            </div>
          )}
          {job.state === 'failed' && (
            <div role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
              {apiErrorMessage(job.error, 400)}
              {canCopy && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="ms-3"
                  onClick={() => copy.mutate()}
                >
                  {t('ui.tryAgain')}
                </Button>
              )}
            </div>
          )}
        </Section>
      )}
    </div>
  )
}

function tableLabel(table: string): string {
  const labels: Record<string, string> = {
    messages: he('Messages'),
    alerts: he('Alerts'),
    jobs: he('Jobs'),
    chats: he('Chats'),
    instances: he('Phone connections'),
    users: he('Users'),
    classifications: he('Classifications'),
    message_receipts: he('Message receipts'),
    settings: he('Settings'),
    stored_media: he('Stored media'),
  }
  return labels[table] ?? table
}
