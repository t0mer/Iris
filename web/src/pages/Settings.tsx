import { apiErrorMessage } from '../lib/apiErrors'
import { t, categoryLabel } from '../lib/i18n'
import { he } from '../lib/he'
import { ParentConnections } from '../components/PhoneConnections'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bell,
  Brain,
  CheckCircle2,
  Clock,
  Database,
  Eye,
  HardDrive,
  KeyRound,
  Loader2,
  RotateCcw,
  Trash2,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { PageHeader } from '../components/PageHeader'
import { PageLoading } from '../components/PageLoading'
import { Section } from '../components/Section'
import { QueryError } from '../components/QueryError'
import { Button } from '../components/ui/button'
import { ConfirmDialog } from '../components/ui/dialog'
import { Field, Input, Select } from '../components/ui/field'
import { Switch } from '../components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import { api, ApiError } from '../lib/api'
import { fileSize } from '../lib/format'
import type { Instance, Stats, ThresholdRow } from '../lib/types'
import { setShowContentByDefault, useShowContentByDefault } from '../lib/prefs'
import { overridesFrom } from '../lib/thresholds'
import { DatabaseTab } from './DatabaseTab'

type Secret = { set: boolean }
interface Values {
  'runtime.classification_provider'?: string
  'runtime.transcription_provider'?: string
  'runtime.ollama_base_url'?: string
  'runtime.ollama_model'?: string
  'runtime.whisper_url'?: string | null
  'runtime.whisper_model'?: string
  'runtime.whisper_fallback_model'?: string | null
  'runtime.whisper_api_key'?: Secret
  'runtime.whisper_use_environment_key'?: boolean
  'runtime.local_safety_mode'?: boolean
  'runtime.require_webhook_signatures'?: boolean
  'runtime.workers'?: number
  'runtime.delivery_workers'?: number
  'runtime.job_heartbeat_seconds'?: number
  'runtime.monitoring_silence_minutes'?: number
  local_providers?: {
    classification: string
    ollama_model: string
    transcription: string
    transcription_model: string
    api_key_set: boolean
  }
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
  'alerts.notify_changes': boolean
  'alerts.timezone': string
  'retention.message_days': number
  'retention.alert_days': number
  'media.policy': 'off' | 'harmful' | 'harmful_review' | 'all'
  'media.backend': 'local' | 's3'
  'media.s3_endpoint': string | null
  'media.s3_bucket': string | null
  'media.s3_region': string
  'media.s3_access_key': string | null
  'media.s3_secret_key': Secret
  'media.s3_prefix': string
  'media.s3_path_style': boolean
  'media.retention_days': number
}
interface TestResult {
  ok: boolean
  detail: string
}
type Change = string | number | boolean | null | Record<string, { low: number; high: number }>

const TABS = [
  'Providers',
  'Classification',
  'Alerts',
  'Scope',
  'Retention',
  'Media',
  'Database',
  'Account',
] as const
type Tab = (typeof TABS)[number]
const SECRETS = [
  'openai.api_key',
  'transcription.cloudflare_api_token',
  'media.s3_secret_key',
  'runtime.whisper_api_key',
]
const NUMBERS = [
  'runtime.workers',
  'runtime.delivery_workers',
  'runtime.job_heartbeat_seconds',
  'runtime.monitoring_silence_minutes',
  'alerts.cooldown_minutes',
  'classification.context_window_size',
  'classification.context_max_age_hours',
  'retention.message_days',
  'retention.alert_days',
  'media.retention_days',
]
const NUMBER_LABELS: Record<string, string> = {
  'alerts.cooldown_minutes': he('Cooldown per chat'),
  'classification.context_window_size': he('Messages of context'),
  'classification.context_max_age_hours': he('Context goes back'),
  'retention.message_days': he('Keep messages for'),
  'retention.alert_days': he('Keep alerts for'),
  'media.retention_days': he('Keep media for'),
}
const BOOLEANS = [
  'runtime.local_safety_mode',
  'runtime.require_webhook_signatures',
  'runtime.whisper_use_environment_key',
  'alerts.alert_on_review',
  'alerts.notify_changes',
  'scope.monitor_from_me',
  'scope.monitor_direct',
  'scope.monitor_groups',
  'media.s3_path_style',
]
const ICON: Record<Tab, LucideIcon> = {
  Providers: KeyRound,
  Classification: Brain,
  Alerts: Bell,
  Scope: Eye,
  Retention: Clock,
  Media: HardDrive,
  Database: Database,
  Account: KeyRound,
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
        placeholder={isSet ? t('settings.secretPlaceholder') : he('Not set')}
        onChange={(e) => onChange(e.target.value)}
      />
      {isSet && (
        <ConfirmDialog
          trigger={<Button variant="outline">{he('Clear')}</Button>}
          title={he('Remove the saved key?')}
          description={he(
            'Iris stops using it until you enter a new one. Checks that need it will fail in the meantime.',
          )}
          confirmLabel={he('Remove key')}
          onConfirm={onClear}
        />
      )}
    </span>
  )
}

/** What is kept right now, and a way to remove all of it (also after keeping was turned off). */
function KeptMedia() {
  const qc = useQueryClient()
  const stats = useQuery({ queryKey: ['stats'], queryFn: () => api<Stats>('/api/stats') })
  const remove = useMutation({
    mutationFn: () => api('/api/media', { method: 'DELETE' }),
    onSuccess: () => {
      toast.success(he('Kept media is being deleted.'))
      return qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : he('Could not delete the media.')),
  })
  const files = stats.data?.media_files ?? 0
  if (files === 0) return null
  return (
    <Section
      title={he('Kept now')}
      description={he('Files stay until their keep time ends, even if you turn keeping off.')}
    >
      <p className="text-sm">
        <span className="tabular font-medium">{files}</span> {he(files === 1 ? 'file' : 'files')},{' '}
        {fileSize(stats.data?.media_bytes ?? 0)}
      </p>
      <ConfirmDialog
        trigger={
          <Button variant="outline" className="w-fit" disabled={remove.isPending}>
            <Trash2 />
            {he('Delete all kept media')}
          </Button>
        }
        title={he('Delete all kept media?')}
        description={he(
          'Every kept photo and voice note is deleted from the storage. The messages and alerts stay.',
        )}
        confirmLabel={he('Delete media')}
        onConfirm={() => remove.mutate()}
      />
    </Section>
  )
}

function TestButton({
  target,
  body,
  label = he('Test'),
}: {
  label?: string
  target: string
  body: Record<string, unknown>
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
        {test.isPending ? he('Testing') : label}
      </Button>
      {test.data && (
        <span
          role="status"
          className={`flex items-center gap-1.5 text-sm ${test.data.ok ? 'text-success' : 'text-danger'}`}
        >
          {test.data.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
          {apiErrorMessage(test.data.detail, test.data.ok ? 200 : 400)}
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
        <span>{he('Category')}</span>
        <span>{he('Needs a look from')}</span>
        <span>{he('Harmful from')}</span>
      </div>
      <ul className="flex flex-col divide-y">
        {data.map((r) => (
          <li
            key={r.category}
            className="grid grid-cols-2 items-center gap-x-3 gap-y-1.5 py-2.5 sm:grid-cols-[1fr_7rem_7rem]"
          >
            <span className="col-span-2 text-sm font-medium sm:col-span-1">
              {categoryLabel(r.category)}
            </span>
            {(['low', 'high'] as const).map((f) => (
              <Input
                key={f}
                className="tabular"
                type="number"
                step="0.01"
                min={0}
                max={1}
                aria-label={`${categoryLabel(r.category)} ${he(f === 'low' ? 'Worth a look' : 'Harmful')}`}
                value={edits[r.category]?.[f] ?? String(r[f])}
                onChange={(e) => onEdit(r.category, f, e.target.value)}
              />
            ))}
          </li>
        ))}
      </ul>
      <Button variant="outline" className="self-start" onClick={onReset}>
        <RotateCcw />
        {he('Reset all to defaults')}
      </Button>
      <p className="max-w-prose text-sm text-muted-foreground">
        {he(
          'A score at or above the harmful level is flagged. Between the two levels Iris is unsure: it looks again with the chat around the message, then asks you to review it if still unclear.',
        )}
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
    if (form.next !== form.confirm) return setMsg(he('The new passwords do not match.'))
    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: form.current, new_password: form.next }),
      })
      setForm({ current: '', next: '', confirm: '' })
      toast.success(he('Password changed. Any other signed-in sessions were signed out.'))
    } catch (err) {
      setMsg(
        err instanceof ApiError ? err.message : he('Could not change the password. Try again.'),
      )
    }
  }
  const showByDefault = useShowContentByDefault()
  return (
    <>
      <Section
        title={he('On this browser')}
        description={he(
          'Stored content (message text, alert quotes, kept photos and voice notes) is hidden until you press the eye. This applies to this browser only.',
        )}
      >
        <Toggle
          label={he('Show content by default')}
          hint={he(
            'Everything starts shown, and you can still hide it with the eye. Leave it off on a shared screen.',
          )}
          checked={showByDefault}
          onChange={setShowContentByDefault}
        />
      </Section>
      <Section
        title={he('Change password')}
        description={he('Use at least 8 characters. Changing it signs out every other browser.')}
      >
        <form onSubmit={submit} className="flex max-w-sm flex-col gap-4">
          <Field label={he('Current password')}>
            <Input
              type="password"
              autoComplete="current-password"
              value={form.current}
              onChange={(e) => setForm({ ...form, current: e.target.value })}
            />
          </Field>
          <Field label={he('New password (at least 8 characters)')}>
            <Input
              type="password"
              autoComplete="new-password"
              value={form.next}
              onChange={(e) => setForm({ ...form, next: e.target.value })}
            />
          </Field>
          <Field label={he('Repeat new password')}>
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
            {he('Change password')}
          </Button>
        </form>
      </Section>
    </>
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
  const [tab, setTab] = useState<Tab>(
    new URLSearchParams(window.location.search).get('tab') === 'Alerts' ? 'Alerts' : 'Providers',
  )
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [thresholdEdits, setThresholdEdits] = useState<
    Record<string, { low: string; high: string }>
  >({})
  const [saving, setSaving] = useState(false)
  if (isError)
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title={he('Settings')} />
        <QueryError what={he('the settings')} onRetry={() => void refetch()} />
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
  const classifier =
    get('runtime.classification_provider') || data.local_providers?.classification || 'openai'
  const provider =
    get('runtime.transcription_provider') ||
    (data.local_providers?.transcription === 'local_whisper'
      ? 'local_whisper'
      : get('transcription.provider'))
  const mediaOn = get('media.policy') !== 'off'

  async function save(changes: Record<string, Change>, clearKeys: string[] = Object.keys(changes)) {
    setSaving(true)
    try {
      await api('/api/settings', { method: 'PUT', body: JSON.stringify({ settings: changes }) })
      // Only the saved keys leave the draft: other unsaved edits survive (e.g. after "Clear").
      setEdit((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !clearKeys.includes(k))))
      if ('classification.thresholds' in changes) setThresholdEdits({})
      await qc.invalidateQueries()
      toast.success(he('Settings saved.'))
    } catch (e) {
      toast.error(
        e instanceof ApiError
          ? t('settings.notSaved', e.message)
          : he('Not saved. Check your connection and try again.'),
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
          toast.error(he('Enter a number for "{name}".', { name: NUMBER_LABELS[k] ?? k }))
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
        he('Thresholds must be numbers from 0 to 1, with "needs a look" lower than "harmful".'),
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
        title={he('Settings')}
        description={he(
          'Providers, how Iris judges messages, where alerts go, and how long things are kept.',
        )}
      />
      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as Tab)}
        orientation="vertical"
        className="flex flex-col gap-5 md:flex-row md:items-start"
      >
        <TabsList
          aria-label={he('Settings sections')}
          className="-mx-4 px-4 md:mx-0 md:w-52 md:shrink-0 md:flex-col md:px-0"
        >
          {TABS.map((t) => {
            const Icon = ICON[t]
            return (
              <TabsTrigger key={t} value={t} className="md:justify-start">
                <span className="flex items-center gap-2">
                  <Icon className="size-4" /> {he(t)}
                </span>
              </TabsTrigger>
            )
          })}
        </TabsList>

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <TabsContent value="Providers" className="flex flex-col gap-5">
            <Section
              title={he('Classification provider')}
              description={he(
                'Choose how Iris classifies messages. Saved choices override server environment defaults.',
              )}
            >
              <Field label={he('Classification provider')}>
                <Select
                  value={classifier}
                  onChange={(e) => set('runtime.classification_provider')(e.target.value)}
                >
                  <option value="openai">OpenAI</option>
                  <option value="ollama">{he('Ollama (local)')}</option>
                </Select>
              </Field>
            </Section>
            {classifier === 'ollama' ? (
              <Section
                title="Ollama"
                description={he(
                  'Local text classifier. Test the entered endpoint and model, then save to use them for new jobs.',
                )}
              >
                <Field label={he('Ollama endpoint')}>
                  <Input
                    value={get('runtime.ollama_base_url')}
                    onChange={(e) => set('runtime.ollama_base_url')(e.target.value)}
                    placeholder="http://localhost:11434"
                  />
                </Field>
                <Field label={he('Ollama model')}>
                  <Input
                    value={get('runtime.ollama_model') || data.local_providers?.ollama_model || ''}
                    onChange={(e) => set('runtime.ollama_model')(e.target.value)}
                  />
                </Field>
                <p className="text-sm text-muted-foreground">
                  {he(
                    'Local scores require calibration. Images and stickers require manual review in local safety mode.',
                  )}
                </p>
                <TestButton
                  target="ollama"
                  body={{
                    base_url: get('runtime.ollama_base_url'),
                    model: get('runtime.ollama_model') || data.local_providers?.ollama_model,
                  }}
                  label={he('Test Ollama')}
                />
              </Section>
            ) : (
              <Section
                title="OpenAI"
                description={he('Checks every message for harm. The moderation endpoint is free.')}
              >
                <Field label={he('API key')}>
                  <SecretInput
                    value={get('openai.api_key')}
                    isSet={data['openai.api_key'].set}
                    onChange={set('openai.api_key')}
                    onClear={() => void save({ 'openai.api_key': null })}
                  />
                </Field>
                <TestButton
                  target="openai"
                  body={{ api_key: edit['openai.api_key'] || undefined }}
                />
              </Section>
            )}
            <Section
              title={he('Transcription provider')}
              description={he(
                'Choose local transcription, OpenAI, or Cloudflare. No automatic cloud fallback is used.',
              )}
            >
              <Field label={he('Provider')}>
                <Select
                  value={provider}
                  onChange={(e) => {
                    const value = e.target.value
                    if ('runtime.transcription_provider' in data || value === 'local_whisper')
                      set('runtime.transcription_provider')(value)
                    if (value !== 'local_whisper') set('transcription.provider')(value)
                  }}
                >
                  <option value="openai">OpenAI</option>
                  <option value="cloudflare">Cloudflare Workers AI</option>
                  <option value="local_whisper">{he('Mila companion / local Whisper')}</option>
                </Select>
              </Field>
            </Section>
            {provider === 'local_whisper' ? (
              <Section
                title={he('Mila companion / local Whisper')}
                description={he(
                  'Active local transcription API. The Mila desktop app itself does not provide this API.',
                )}
              >
                <Field label={he('Transcription endpoint')}>
                  <Input
                    value={get('runtime.whisper_url')}
                    onChange={(e) => set('runtime.whisper_url')(e.target.value)}
                    placeholder="http://mac.example:8081/v1/audio/transcriptions"
                  />
                </Field>
                <Field label={he('Local transcription model')}>
                  <Input
                    list="whisper-models"
                    value={
                      get('runtime.whisper_model') ||
                      data.local_providers?.transcription_model ||
                      ''
                    }
                    onChange={(e) => set('runtime.whisper_model')(e.target.value)}
                  />
                </Field>
                <datalist id="whisper-models">
                  <option value="auto" />
                  <option value="ivrit-large-v3" />
                  <option value="large-v3-turbo" />
                </datalist>
                <Field label={he('Local transcription API key')}>
                  <SecretInput
                    value={get('runtime.whisper_api_key')}
                    isSet={data['runtime.whisper_api_key']?.set || false}
                    onChange={set('runtime.whisper_api_key')}
                    onClear={() =>
                      void save({
                        'runtime.whisper_api_key': null,
                        'runtime.whisper_use_environment_key': false,
                      })
                    }
                  />
                </Field>
                <Toggle
                  label={he('Use environment API key when no saved key exists')}
                  checked={get('runtime.whisper_use_environment_key') !== 'false'}
                  onChange={(value) => set('runtime.whisper_use_environment_key')(String(value))}
                />
                <Field label={he('Fallback model (optional)')}>
                  <Input
                    value={get('runtime.whisper_fallback_model')}
                    onChange={(e) => set('runtime.whisper_fallback_model')(e.target.value)}
                  />
                </Field>
                <p className="text-sm text-muted-foreground">
                  {he(
                    'Audio and video audio tracks are transcribed. Test the endpoint, model and key before saving. Changing the host requires re-entering the API key.',
                  )}
                </p>
                <TestButton
                  target="local_whisper"
                  body={{
                    endpoint: get('runtime.whisper_url'),
                    model:
                      get('runtime.whisper_model') || data.local_providers?.transcription_model,
                    api_key: edit['runtime.whisper_api_key'] || undefined,
                  }}
                  label={he('Test transcription connection')}
                />
              </Section>
            ) : (
              <Section
                title={he('Voice and video')}
                description={he('Turns audio into text so it can be checked like any message.')}
              >
                {provider === 'openai' ? (
                  <Field label={he('OpenAI model')}>
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
                    <Field label={he('Cloudflare account ID')}>
                      <Input
                        dir="ltr"
                        value={get('transcription.cloudflare_account_id')}
                        onChange={(e) => set('transcription.cloudflare_account_id')(e.target.value)}
                      />
                    </Field>
                    <Field label={he('Cloudflare API token')}>
                      <SecretInput
                        value={get('transcription.cloudflare_api_token')}
                        isSet={data['transcription.cloudflare_api_token'].set}
                        onChange={set('transcription.cloudflare_api_token')}
                        onClear={() => void save({ 'transcription.cloudflare_api_token': null })}
                      />
                    </Field>
                    <Field label={he('Model')}>
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
            )}
          </TabsContent>

          <TabsContent value="Classification" className="flex flex-col gap-5">
            <Section
              title={he('Processing mode')}
              description={he(
                'Safety mode keeps unexamined media for review. Worker changes apply to new jobs; in-flight jobs finish.',
              )}
            >
              <Toggle
                label={he('Local safety mode')}
                checked={get('runtime.local_safety_mode') === 'true'}
                onChange={(value) => set('runtime.local_safety_mode')(String(value))}
              />
              <Toggle
                label={he('Require signed webhooks')}
                checked={get('runtime.require_webhook_signatures') === 'true'}
                onChange={(value) => set('runtime.require_webhook_signatures')(String(value))}
              />
              {num('runtime.workers', he('Classification workers (0 pauses processing)'), 0, 16)}
              {num('runtime.delivery_workers', he('Dedicated alert workers'), 0, 4)}
              {num(
                'runtime.job_heartbeat_seconds',
                he('Job heartbeat seconds (0 disables)'),
                0,
                120,
              )}
              {num(
                'runtime.monitoring_silence_minutes',
                he('Monitoring silence minutes (0 disables)'),
                0,
                10080,
              )}
            </Section>
            <Section
              title={he('Moderation')}
              description={he(
                'How much of the chat Iris reads around a message it is unsure about.',
              )}
            >
              <Field label={he('OpenAI moderation model')}>
                <Input
                  dir="ltr"
                  value={get('classification.model')}
                  onChange={(e) => set('classification.model')(e.target.value)}
                />
              </Field>
              {num(
                'classification.context_window_size',
                he('Messages of context (1 to 20)'),
                1,
                20,
              )}
              {num('classification.context_max_age_hours', he('Context goes back (hours)'), 1, 168)}
            </Section>
            <Section
              title={he('Thresholds')}
              description={he('Scores are 0 to 1. Lower numbers make Iris more cautious.')}
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
            <ParentConnections />
            <Section
              title={he('Where alerts go')}
              description={he(
                'Iris sends each alert to every listed parent from one linked WhatsApp phone. Up to 10 recipients.',
              )}
            >
              <Field label={he('Send alerts from')}>
                <Select
                  value={get('alerts.sender_instance_id')}
                  onChange={(e) => set('alerts.sender_instance_id')(e.target.value)}
                >
                  <option value="">{he('Not set')}</option>
                  {instances?.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.kid_name}
                    </option>
                  ))}
                </Select>
              </Field>
              <TestButton
                target="alert"
                body={{
                  sender_instance_id: get('alerts.sender_instance_id') || undefined,
                  recipient: get('alerts.recipient') || undefined,
                }}
              />
            </Section>
            <Section title={he('Frequency and timing')}>
              {num('alerts.cooldown_minutes', he('Cooldown per chat (minutes)'), 0, 1440)}
              <Field label={he('Time zone')}>
                <Input
                  dir="ltr"
                  value={get('alerts.timezone')}
                  onChange={(e) => set('alerts.timezone')(e.target.value)}
                />
              </Field>
              {bool(
                'alerts.alert_on_review',
                he('Also alert on items needing review'),
                he('Off by default: those wait in the Review page instead.'),
              )}
              {bool(
                'alerts.notify_changes',
                he('Tell me when an alerted message is edited or deleted'),
                he('Sends a short follow-up on WhatsApp. It never repeats the message.'),
              )}
            </Section>
          </TabsContent>

          <TabsContent value="Scope" className="flex flex-col gap-5">
            <Section
              title={he('What to watch')}
              description={he('Turn off anything you do not want Iris to check.')}
            >
              <div className="flex flex-col divide-y">
                {bool('scope.monitor_from_me', he('Messages the child sends'))}
                {bool('scope.monitor_direct', he('Direct chats'))}
                {bool('scope.monitor_groups', he('Groups'))}
              </div>
            </Section>
          </TabsContent>

          <TabsContent value="Retention" className="flex flex-col gap-5">
            <Section
              title={he('How long to keep things')}
              description={he(
                'Messages tied to an alert are kept until that alert expires. Kept media has its own limit under Media.',
              )}
            >
              {num('retention.message_days', he('Keep messages for (days)'), 1)}
              {num('retention.alert_days', he('Keep alerts for (days)'), 1)}
            </Section>
          </TabsContent>

          <TabsContent value="Media" className="flex flex-col gap-5">
            <Section
              title={he('Keep media')}
              description={he(
                'By default Iris deletes every photo and voice note as soon as it has been checked. Turn this on to keep copies you can open from alerts.',
              )}
            >
              <Toggle
                label={he('Keep media')}
                hint={he('Files can only be opened after you sign in to Iris.')}
                checked={mediaOn}
                onChange={(on) => set('media.policy')(on ? 'harmful' : 'off')}
              />
              {mediaOn && (
                <fieldset className="flex flex-col gap-2">
                  <legend className="mb-1 text-sm font-medium">{he('What to keep')}</legend>
                  {(
                    [
                      [
                        'harmful',
                        he('Only what Iris judges harmful'),
                        he('The media behind your alerts.'),
                      ],
                      [
                        'harmful_review',
                        he('Harmful and needs a look'),
                        he('Also the items waiting in the review queue.'),
                      ],
                      [
                        'all',
                        he('Everything'),
                        he('Every photo and voice note. Uses the most space.'),
                      ],
                    ] as const
                  ).map(([value, label, hint]) => (
                    <label key={value} className="flex items-start gap-3 text-sm">
                      <input
                        type="radio"
                        name="media-policy"
                        className="mt-1 size-4 accent-[var(--color-primary)]"
                        checked={get('media.policy') === value}
                        onChange={() => set('media.policy')(value)}
                      />
                      <span className="flex flex-col">
                        <span className="font-medium">{label}</span>
                        <span className="text-muted-foreground">{hint}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
              )}
              <p className="max-w-prose text-sm text-muted-foreground">
                {he(
                  'Content Iris withholds (anything sexual involving minors, or sexual images) is never kept, whatever you choose. Videos are not kept at all, because Iris checks what a video says, not what it shows.',
                )}
              </p>
            </Section>
            <KeptMedia />

            {mediaOn && (
              <>
                <Section title={he('Where to keep it')}>
                  <Field label={he('Storage')} className="max-w-72">
                    <Select
                      value={get('media.backend')}
                      onChange={(e) => set('media.backend')(e.target.value)}
                    >
                      <option value="local">{he('This server&apos;s disk')}</option>
                      <option value="s3">{he('S3-compatible storage')}</option>
                    </Select>
                  </Field>
                  {get('media.backend') === 'local' ? (
                    <p className="max-w-prose text-sm text-muted-foreground">
                      {he('Files go to the')}
                      <code>media</code>
                      {he(
                        'folder inside Iris&apos;s data folder, next to the database. In Docker that is the data volume.',
                      )}
                    </p>
                  ) : (
                    <>
                      <p className="max-w-prose text-sm text-muted-foreground">
                        {he(
                          'Works with Cloudflare R2, AWS S3, SeaweedFS, MinIO and other S3-compatible services. Create the bucket first.',
                        )}
                      </p>
                      <Field
                        label={he('Endpoint')}
                        hint={he(
                          'For example https://ACCOUNT.r2.cloudflarestorage.com, https://s3.eu-west-1.amazonaws.com or http://seaweed.lan:8333',
                        )}
                      >
                        <Input
                          dir="ltr"
                          value={get('media.s3_endpoint')}
                          onChange={(e) => set('media.s3_endpoint')(e.target.value)}
                          autoComplete="off"
                        />
                      </Field>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label={he('Bucket')}>
                          <Input
                            dir="ltr"
                            value={get('media.s3_bucket')}
                            onChange={(e) => set('media.s3_bucket')(e.target.value)}
                            autoComplete="off"
                          />
                        </Field>
                        <Field label={he('Region')} hint={he('Use auto for Cloudflare R2.')}>
                          <Input
                            dir="ltr"
                            value={get('media.s3_region')}
                            onChange={(e) => set('media.s3_region')(e.target.value)}
                            autoComplete="off"
                          />
                        </Field>
                      </div>
                      <Field label={he('Access key ID')}>
                        <Input
                          dir="ltr"
                          value={get('media.s3_access_key')}
                          onChange={(e) => set('media.s3_access_key')(e.target.value)}
                          autoComplete="off"
                        />
                      </Field>
                      <Field label={he('Secret access key')}>
                        <SecretInput
                          value={get('media.s3_secret_key')}
                          isSet={data['media.s3_secret_key'].set}
                          onChange={set('media.s3_secret_key')}
                          onClear={() => void save({ 'media.s3_secret_key': null })}
                        />
                      </Field>
                      <Field
                        label={he('Folder in the bucket')}
                        hint={he('Optional. Everything is kept under it.')}
                      >
                        <Input
                          dir="ltr"
                          value={get('media.s3_prefix')}
                          onChange={(e) => set('media.s3_prefix')(e.target.value)}
                          autoComplete="off"
                        />
                      </Field>
                      {bool(
                        'media.s3_path_style',
                        he('Path-style addresses'),
                        he(
                          'Keep this on for R2, SeaweedFS and MinIO. Turn it off for AWS S3 buckets that need bucket.host addresses.',
                        ),
                      )}
                    </>
                  )}
                  <TestButton
                    target="media"
                    body={{
                      media: {
                        backend: get('media.backend'),
                        endpoint: get('media.s3_endpoint') || undefined,
                        bucket: get('media.s3_bucket') || undefined,
                        region: get('media.s3_region') || undefined,
                        access_key: get('media.s3_access_key') || undefined,
                        secret_key: edit['media.s3_secret_key'] || undefined,
                        prefix: get('media.s3_prefix'),
                        path_style: get('media.s3_path_style') === 'true',
                      },
                    }}
                    label={he('Test storage')}
                  />
                </Section>

                <Section title={he('How long to keep it')}>
                  {num('media.retention_days', he('Keep media for (days)'), 1)}
                  <p className="max-w-prose text-sm text-muted-foreground">
                    {he(
                      'Older files are deleted from the storage. The message and its alert stay until their own limits under Retention.',
                    )}
                  </p>
                </Section>
              </>
            )}
          </TabsContent>

          <TabsContent value="Database">
            <DatabaseTab />
          </TabsContent>

          <TabsContent value="Account">
            <Account />
          </TabsContent>

          {dirty && tab !== 'Account' && tab !== 'Database' && (
            <div className="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-surface p-3 shadow-overlay md:bottom-4">
              <p className="text-sm text-muted-foreground">{he('You have unsaved changes.')}</p>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setEdit({})
                    setThresholdEdits({})
                  }}
                >
                  {he('Discard')}
                </Button>
                <Button variant="primary" onClick={saveAll} disabled={saving}>
                  {saving && <Loader2 className="animate-spin" />}
                  {he('Save')}
                </Button>
              </div>
            </div>
          )}
        </div>
      </Tabs>
    </div>
  )
}
