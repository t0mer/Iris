import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bell,
  Brain,
  CheckCircle2,
  Clock,
  Eye,
  KeyRound,
  Loader2,
  RotateCcw,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { toast } from 'sonner'
import { PageHeader } from '../components/PageHeader'
import { PageLoading } from '../components/PageLoading'
import { QueryError } from '../components/QueryError'
import { Button } from '../components/ui/button'
import { ConfirmDialog } from '../components/ui/dialog'
import { Field, Input, Select } from '../components/ui/field'
import { Switch } from '../components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import { api, ApiError } from '../lib/api'
import type { Instance, ThresholdRow } from '../lib/types'
import { overridesFrom } from '../lib/thresholds'

type Secret = { set: boolean }
interface Values {
  'openai.api_key': Secret
  'transcription.provider': 'openai' | 'cloudflare'
  'transcription.openai_model': string
  'transcription.cloudflare_account_id': string | null
  'transcription.cloudflare_api_token': Secret
  'transcription.cloudflare_model': string
  'classification.model': string
  'classification.context_window_size': number
  'classification.context_max_age_hours': number
  'scope.monitor_from_me': boolean
  'scope.monitor_direct': boolean
  'scope.monitor_groups': boolean
  'alerts.sender_instance_id': number | null
  'alerts.recipient': string | null
  'alerts.cooldown_minutes': number
  'alerts.alert_on_review': boolean
  'alerts.timezone': string
  'retention.message_days': number
  'retention.alert_days': number
}
interface TestResult {
  ok: boolean
  detail: string
}
type Change = string | number | boolean | null | Record<string, { low: number; high: number }>

const TABS = ['Providers', 'Classification', 'Alerts', 'Scope', 'Retention', 'Account'] as const
type Tab = (typeof TABS)[number]
const SECRETS = ['openai.api_key', 'transcription.cloudflare_api_token']
const NUMBERS = [
  'alerts.cooldown_minutes',
  'classification.context_window_size',
  'classification.context_max_age_hours',
  'retention.message_days',
  'retention.alert_days',
]
const NUMBER_LABELS: Record<string, string> = {
  'alerts.cooldown_minutes': 'Cooldown per chat',
  'classification.context_window_size': 'Messages of context',
  'classification.context_max_age_hours': 'Context goes back',
  'retention.message_days': 'Keep messages for',
  'retention.alert_days': 'Keep alerts for',
}
const BOOLEANS = [
  'alerts.alert_on_review',
  'scope.monitor_from_me',
  'scope.monitor_direct',
  'scope.monitor_groups',
]
const ICON: Record<Tab, LucideIcon> = {
  Providers: KeyRound,
  Classification: Brain,
  Alerts: Bell,
  Scope: Eye,
  Retention: Clock,
  Account: KeyRound,
}

function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">{title}</h2>
        {description && <p className="max-w-prose text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  )
}

function SecretInput({
  value,
  isSet,
  onChange,
  onClear,
}: {
  value: string
  isSet: boolean
  onChange: (v: string) => void
  onClear: () => void
}) {
  return (
    <span className="flex items-center gap-2">
      <Input
        type="password"
        autoComplete="off"
        value={value}
        placeholder={isSet ? '•••••••• (saved, leave blank to keep)' : 'Not set'}
        onChange={(e) => onChange(e.target.value)}
      />
      {isSet && (
        <ConfirmDialog
          trigger={<Button variant="outline">Clear</Button>}
          title="Remove the saved key?"
          description="Iris stops using it until you enter a new one. Checks that need it will fail in the meantime."
          confirmLabel="Remove key"
          onConfirm={onClear}
        />
      )}
    </span>
  )
}

function TestButton({
  target,
  body,
}: {
  target: string
  body: Record<string, string | undefined>
}) {
  const test = useMutation({
    mutationFn: () =>
      api<TestResult>(`/api/settings/test/${target}`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  })
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
        {test.isPending && <Loader2 className="animate-spin" />}{' '}
        {test.isPending ? 'Testing' : 'Test'}
      </Button>
      {test.data && (
        <span
          role="status"
          className={`flex items-center gap-1.5 text-sm ${test.data.ok ? 'text-success' : 'text-danger'}`}
        >
          {test.data.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
          {test.data.detail}
        </span>
      )}
      {test.error && <span className="text-sm text-danger">{String(test.error.message)}</span>}
    </div>
  )
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string
  hint?: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-start justify-between gap-4 py-1 text-sm">
      <span className="flex flex-col gap-0.5">
        <span className="font-medium">{label}</span>
        {hint && <span className="text-muted-foreground">{hint}</span>}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
    </label>
  )
}

function ThresholdsTable({
  edits,
  onEdit,
  onReset,
}: {
  edits: Record<string, { low: string; high: string }>
  onEdit: (cat: string, field: 'low' | 'high', v: string) => void
  onReset: () => void
}) {
  const { data } = useQuery({
    queryKey: ['thresholds'],
    queryFn: () => api<ThresholdRow[]>('/api/settings/thresholds'),
  })
  if (!data) return null
  return (
    <div className="flex flex-col gap-3">
      <div className="hidden grid-cols-[1fr_7rem_7rem] gap-3 px-1 text-sm font-medium text-muted-foreground sm:grid">
        <span>Category</span>
        <span>Needs a look from</span>
        <span>Harmful from</span>
      </div>
      <ul className="flex flex-col divide-y">
        {data.map((r) => (
          <li
            key={r.category}
            className="grid grid-cols-2 items-center gap-x-3 gap-y-1.5 py-2.5 sm:grid-cols-[1fr_7rem_7rem]"
          >
            <span className="col-span-2 text-sm font-medium sm:col-span-1">{r.category}</span>
            {(['low', 'high'] as const).map((f) => (
              <Input
                key={f}
                className="tabular"
                type="number"
                step="0.01"
                min={0}
                max={1}
                aria-label={`${r.category} ${f}`}
                value={edits[r.category]?.[f] ?? String(r[f])}
                onChange={(e) => onEdit(r.category, f, e.target.value)}
              />
            ))}
          </li>
        ))}
      </ul>
      <Button variant="outline" className="self-start" onClick={onReset}>
        <RotateCcw /> Reset all to defaults
      </Button>
      <p className="max-w-prose text-sm text-muted-foreground">
        A score at or above the harmful level is flagged. Between the two levels Iris is unsure: it
        looks again with the chat around the message, then asks you to review it if still unclear.
      </p>
    </div>
  )
}

function Account() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setMsg(null)
    if (form.next !== form.confirm) return setMsg('The new passwords do not match.')
    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: form.current, new_password: form.next }),
      })
      setForm({ current: '', next: '', confirm: '' })
      toast.success('Password changed. Any other signed-in sessions were signed out.')
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : 'Could not change the password. Try again.')
    }
  }
  return (
    <Section
      title="Change password"
      description="Use at least 8 characters. Changing it signs out every other browser."
    >
      <form onSubmit={submit} className="flex max-w-sm flex-col gap-4">
        <Field label="Current password">
          <Input
            type="password"
            autoComplete="current-password"
            value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })}
          />
        </Field>
        <Field label="New password (at least 8 characters)">
          <Input
            type="password"
            autoComplete="new-password"
            value={form.next}
            onChange={(e) => setForm({ ...form, next: e.target.value })}
          />
        </Field>
        <Field label="Repeat new password">
          <Input
            type="password"
            autoComplete="new-password"
            value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })}
          />
        </Field>
        {msg && (
          <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
            {msg}
          </p>
        )}
        <Button type="submit" variant="primary" className="self-start">
          Change password
        </Button>
      </form>
    </Section>
  )
}

export function Settings() {
  const qc = useQueryClient()
  const { data, isError, refetch } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Values>('/api/settings'),
  })
  const { data: instances } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const { data: thresholdRows } = useQuery({
    queryKey: ['thresholds'],
    queryFn: () => api<ThresholdRow[]>('/api/settings/thresholds'),
  })
  const [tab, setTab] = useState<Tab>('Providers')
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [thresholdEdits, setThresholdEdits] = useState<
    Record<string, { low: string; high: string }>
  >({})
  const [saving, setSaving] = useState(false)
  if (isError)
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title="Settings" />
        <QueryError what="the settings" onRetry={() => void refetch()} />
      </div>
    )
  if (!data) return <PageLoading />

  // Secrets are write-only: the API only says whether they are set, so the field starts blank.
  const get = (k: keyof Values): string => {
    if (k in edit) return edit[k]
    const v = data[k]
    return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : ''
  }
  const set = (k: keyof Values) => (v: string) => setEdit((e) => ({ ...e, [k]: v }))
  const provider = get('transcription.provider')

  async function save(changes: Record<string, Change>, clearKeys: string[] = Object.keys(changes)) {
    setSaving(true)
    try {
      await api('/api/settings', { method: 'PUT', body: JSON.stringify({ settings: changes }) })
      // Only the saved keys leave the draft: other unsaved edits survive (e.g. after "Clear").
      setEdit((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !clearKeys.includes(k))))
      if ('classification.thresholds' in changes) setThresholdEdits({})
      await qc.invalidateQueries()
      toast.success('Settings saved.')
    } catch (e) {
      toast.error(
        e instanceof ApiError
          ? `Not saved: ${e.message}`
          : 'Not saved. Check your connection and try again.',
      )
    } finally {
      setSaving(false)
    }
  }

  const thresholdOverrides = () => overridesFrom(thresholdRows, thresholdEdits)

  function saveAll() {
    const changes: Record<string, Change> = {}
    for (const [k, v] of Object.entries(edit)) {
      if (SECRETS.includes(k) && v === '') continue // blank secret = keep
      if (NUMBERS.includes(k)) {
        if (v.trim() === '' || !Number.isFinite(Number(v))) {
          toast.error(`Enter a number for "${NUMBER_LABELS[k] ?? k}".`)
          return
        }
        changes[k] = Number(v)
      } else if (k === 'alerts.sender_instance_id') changes[k] = v === '' ? null : Number(v)
      else if (BOOLEANS.includes(k)) changes[k] = v === 'true'
      else changes[k] = v
    }
    const overrides = thresholdOverrides()
    if (overrides === 'invalid') {
      toast.error(
        'Thresholds must be numbers from 0 to 1, with "needs a look" lower than "harmful".',
      )
      return
    }
    if (overrides) changes['classification.thresholds'] = overrides
    if (Object.keys(changes).length === 0) {
      setEdit({}) // nothing but blank secrets was pending: there is nothing to send
      return
    }
    void save(changes, Object.keys(edit)) // every processed key leaves the draft, blank secrets too
  }

  const dirty = Object.keys(edit).length > 0 || Object.keys(thresholdEdits).length > 0
  const bool = (k: keyof Values, label: string, hint?: string) => (
    <Toggle
      label={label}
      hint={hint}
      checked={get(k) === 'true'}
      onChange={(v) => set(k)(String(v))}
    />
  )
  const num = (k: keyof Values, label: string, min: number, max?: number) => (
    <Field label={label} className="max-w-48">
      <Input
        className="tabular"
        type="number"
        min={min}
        max={max}
        value={get(k)}
        onChange={(e) => set(k)(e.target.value)}
      />
    </Field>
  )

  return (
    <div className="flex max-w-5xl flex-col gap-5">
      <PageHeader
        title="Settings"
        description="Providers, how Iris judges messages, where alerts go, and how long things are kept."
      />
      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as Tab)}
        orientation="vertical"
        className="flex flex-col gap-5 md:flex-row md:items-start"
      >
        <TabsList
          aria-label="Settings sections"
          className="-mx-4 px-4 md:mx-0 md:w-52 md:shrink-0 md:flex-col md:px-0"
        >
          {TABS.map((t) => {
            const Icon = ICON[t]
            return (
              <TabsTrigger key={t} value={t} className="md:justify-start">
                <span className="flex items-center gap-2">
                  <Icon className="size-4" /> {t}
                </span>
              </TabsTrigger>
            )
          })}
        </TabsList>

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <TabsContent value="Providers" className="flex flex-col gap-5">
            <Section
              title="OpenAI"
              description="Checks every message for harm. The moderation endpoint is free."
            >
              <Field label="API key">
                <SecretInput
                  value={get('openai.api_key')}
                  isSet={data['openai.api_key'].set}
                  onChange={set('openai.api_key')}
                  onClear={() => void save({ 'openai.api_key': null })}
                />
              </Field>
              <TestButton target="openai" body={{ api_key: edit['openai.api_key'] || undefined }} />
            </Section>
            <Section
              title="Voice and video"
              description="Turns audio into text so it can be checked like any message."
            >
              <Field label="Provider">
                <Select
                  value={provider}
                  onChange={(e) => set('transcription.provider')(e.target.value)}
                >
                  <option value="openai">OpenAI</option>
                  <option value="cloudflare">Cloudflare Workers AI</option>
                </Select>
              </Field>
              {provider === 'openai' ? (
                <Field label="OpenAI model">
                  <Select
                    value={get('transcription.openai_model')}
                    onChange={(e) => set('transcription.openai_model')(e.target.value)}
                  >
                    <option value="gpt-4o-mini-transcribe">gpt-4o-mini-transcribe</option>
                    <option value="whisper-1">whisper-1</option>
                  </Select>
                </Field>
              ) : (
                <>
                  <Field label="Cloudflare account ID">
                    <Input
                      dir="ltr"
                      value={get('transcription.cloudflare_account_id')}
                      onChange={(e) => set('transcription.cloudflare_account_id')(e.target.value)}
                    />
                  </Field>
                  <Field label="Cloudflare API token">
                    <SecretInput
                      value={get('transcription.cloudflare_api_token')}
                      isSet={data['transcription.cloudflare_api_token'].set}
                      onChange={set('transcription.cloudflare_api_token')}
                      onClear={() => void save({ 'transcription.cloudflare_api_token': null })}
                    />
                  </Field>
                  <Field label="Model">
                    <Input
                      dir="ltr"
                      value={get('transcription.cloudflare_model')}
                      onChange={(e) => set('transcription.cloudflare_model')(e.target.value)}
                    />
                  </Field>
                  <TestButton
                    target="cloudflare"
                    body={{
                      account_id: edit['transcription.cloudflare_account_id'] || undefined,
                      api_token: edit['transcription.cloudflare_api_token'] || undefined,
                      model: edit['transcription.cloudflare_model'] || undefined,
                    }}
                  />
                </>
              )}
            </Section>
          </TabsContent>

          <TabsContent value="Classification" className="flex flex-col gap-5">
            <Section
              title="Moderation"
              description="How much of the chat Iris reads around a message it is unsure about."
            >
              <Field label="Moderation model">
                <Input
                  dir="ltr"
                  value={get('classification.model')}
                  onChange={(e) => set('classification.model')(e.target.value)}
                />
              </Field>
              {num('classification.context_window_size', 'Messages of context (1 to 20)', 1, 20)}
              {num('classification.context_max_age_hours', 'Context goes back (hours)', 1, 168)}
            </Section>
            <Section
              title="Thresholds"
              description="Scores are 0 to 1. Lower numbers make Iris more cautious."
            >
              <ThresholdsTable
                edits={thresholdEdits}
                onEdit={(cat, f, v) =>
                  setThresholdEdits((e) => {
                    const row = thresholdRows?.find((r) => r.category === cat)
                    const cur = e[cat] ?? {
                      low: String(row?.low ?? ''),
                      high: String(row?.high ?? ''),
                    }
                    return { ...e, [cat]: { ...cur, [f]: v } }
                  })
                }
                onReset={() => void save({ 'classification.thresholds': {} })}
              />
            </Section>
          </TabsContent>

          <TabsContent value="Alerts" className="flex flex-col gap-5">
            <Section
              title="Where alerts go"
              description="Iris sends each alert as a WhatsApp message from one of your phones to your own number."
            >
              <Field label="Send alerts from">
                <Select
                  value={get('alerts.sender_instance_id')}
                  onChange={(e) => set('alerts.sender_instance_id')(e.target.value)}
                >
                  <option value="">Not set</option>
                  {instances?.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.kid_name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Recipient (phone number in international format, or a chat ID)">
                <Input
                  dir="ltr"
                  placeholder="972501234567"
                  value={get('alerts.recipient')}
                  onChange={(e) => set('alerts.recipient')(e.target.value)}
                />
              </Field>
              <TestButton
                target="alert"
                body={{
                  sender_instance_id: get('alerts.sender_instance_id') || undefined,
                  recipient: get('alerts.recipient') || undefined,
                }}
              />
            </Section>
            <Section title="Frequency and timing">
              {num('alerts.cooldown_minutes', 'Cooldown per chat (minutes)', 0, 1440)}
              <Field label="Time zone">
                <Input
                  dir="ltr"
                  value={get('alerts.timezone')}
                  onChange={(e) => set('alerts.timezone')(e.target.value)}
                />
              </Field>
              {bool(
                'alerts.alert_on_review',
                'Also alert on items needing review',
                'Off by default: those wait in the Review page instead.',
              )}
            </Section>
          </TabsContent>

          <TabsContent value="Scope" className="flex flex-col gap-5">
            <Section
              title="What to watch"
              description="Turn off anything you do not want Iris to check."
            >
              <div className="flex flex-col divide-y">
                {bool('scope.monitor_from_me', 'Messages the child sends')}
                {bool('scope.monitor_direct', 'Direct chats')}
                {bool('scope.monitor_groups', 'Groups')}
              </div>
            </Section>
          </TabsContent>

          <TabsContent value="Retention" className="flex flex-col gap-5">
            <Section
              title="How long to keep things"
              description="Messages tied to an alert are kept until that alert expires. Media is never stored beyond processing."
            >
              {num('retention.message_days', 'Keep messages for (days)', 1)}
              {num('retention.alert_days', 'Keep alerts for (days)', 1)}
            </Section>
          </TabsContent>

          <TabsContent value="Account">
            <Account />
          </TabsContent>

          {dirty && tab !== 'Account' && (
            <div className="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-20 flex items-center justify-between gap-3 rounded-lg border bg-surface p-3 shadow-overlay md:bottom-4">
              <p className="text-sm text-muted-foreground">You have unsaved changes.</p>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setEdit({})
                    setThresholdEdits({})
                  }}
                >
                  Discard
                </Button>
                <Button variant="primary" onClick={saveAll} disabled={saving}>
                  {saving && <Loader2 className="animate-spin" />} Save
                </Button>
              </div>
            </div>
          )}
        </div>
      </Tabs>
    </div>
  )
}
