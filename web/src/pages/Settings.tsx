import { t as translate, useLanguage } from '../lib/i18n'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { ParentConnections } from '../components/PhoneConnections'
import { AlertDeliveryHealth } from '../components/AlertDeliveryHealth'
import { SystemNotifications } from '../components/SystemNotifications'
import { OllamaModelPicker } from '../components/OllamaModelPicker'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Brain,
  CheckCircle2,
  CalendarClock,
  ScrollText,
  Database,
  Eye,
  HardDrive,
  KeyRound,
  Loader2,
  Mail,
  User,
  RotateCcw,
  Trash2,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { toast } from '../lib/notify'
import { PageHeader } from '../components/PageHeader'
import { PageLoading } from '../components/PageLoading'
import { Section, SectionGroup } from '../components/Section'
import { ChoiceCards } from '../components/ChoiceCards'
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
import { UserSettings } from './UserSettings'
import { ProviderHealth } from '../components/ProviderHealth'
import { NotificationsSettings } from './NotificationsSettings'
import { DatabaseTab } from './DatabaseTab'
import { ScheduleSettings } from './ScheduleSettings'
import { AuditSettings } from './AuditSettings'
import { LearningSettings } from './LearningSettings'

type Secret = { set: boolean }
interface Values {
  'openwa.webhook_attempts'?: number
  'openwa.recovery_enabled'?: boolean
  'openwa.recovery_hours'?: number
  'runtime.public_base_url'?: string
  'runtime.webhook_base_url'?: string | null
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
  provider_media?: {
    archive_enabled: boolean | null
    archive_outbound: boolean | null
    archive_ttl_days: number | null
    download_timeout_seconds: number | null
    managed_by: string
  }
  'media.recovery_attempts': number
  'media.recovery_wait_seconds': number
  'openai.api_key': Secret
  'transcription.provider': 'openai' | 'cloudflare'
  'transcription.openai_model': string
  'transcription.cloudflare_account_id': string | null
  'transcription.cloudflare_api_token': Secret
  'transcription.cloudflare_model': string
  'classification.model': string
  'classification.learning_mode'?: 'off' | 'shadow' | 'active'
  'classification.community_learning'?: boolean
  'classification.learning_retrieval'?: 'lexical' | 'semantic'
  'classification.learning_embedding_model'?: string | null
  'classification.learning_min_similarity'?: number
  'classification.context_window_size': number
  'classification.context_max_age_hours': number
  'scope.monitor_from_me': boolean
  'scope.monitor_direct': boolean
  'scope.monitor_groups': boolean
  'alerts.sender_instance_id': number | null
  'alerts.recipient': string | null
  'alerts.channel': 'openwa' | 'telegram' | 'smtp' | 'greenapi'
  'alerts.telegram_bot_token': Secret
  'auth.default_channel': 'email' | 'whatsapp'
  'alerts.review_buttons': boolean
  'alerts.notification_style': 'summary' | 'detailed'
  'retention.message_hours': number
  'media.retention_hours': number
  'alerts.send_interval_seconds': number
  'alerts.send_hourly_limit': number
  'alerts.send_daily_limit': number
  'alerts.provider_notification_minutes': number
  'alerts.provider_notification_channel': string
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
  'Scope',
  'Retention',
  'Schedules',
  'Audit',
  'Media',
  'Database',
  'Users',
  'Notifications',
] as const
type Tab = (typeof TABS)[number]
const SECRETS = [
  'openai.api_key',
  'transcription.cloudflare_api_token',
  'media.s3_secret_key',
  'runtime.whisper_api_key',
  'alerts.telegram_bot_token',
]
const NUMBERS = [
  'openwa.webhook_attempts',
  'openwa.recovery_hours',
  'runtime.workers',
  'runtime.delivery_workers',
  'runtime.job_heartbeat_seconds',
  'runtime.monitoring_silence_minutes',
  'alerts.send_interval_seconds',
  'alerts.send_hourly_limit',
  'alerts.send_daily_limit',
  'alerts.cooldown_minutes',
  'alerts.provider_notification_minutes',
  'classification.context_window_size',
  'classification.context_max_age_hours',
  'classification.learning_min_similarity',
  'retention.message_days',
  'retention.message_hours',
  'media.retention_hours',
  'retention.alert_days',
  'media.retention_days',
  'media.recovery_attempts',
  'media.recovery_wait_seconds',
]
const NUMBER_LABELS: Record<string, string> = {
  'alerts.send_interval_seconds': 'Interval between sends',
  'alerts.send_hourly_limit': 'Hourly send limit',
  'alerts.send_daily_limit': 'Daily send limit',
  'alerts.cooldown_minutes': 'Cooldown per chat',
  'classification.context_window_size': 'Messages of context',
  'classification.context_max_age_hours': 'Context goes back',
  'retention.message_days': 'Keep messages for',
  'retention.alert_days': 'Keep alerts for',
  'media.retention_days': 'Keep media for',
}
const BOOLEANS = [
  'openwa.recovery_enabled',
  'runtime.local_safety_mode',
  'runtime.require_webhook_signatures',
  'runtime.whisper_use_environment_key',
  'alerts.alert_on_review',
  'alerts.notify_changes',
  'alerts.review_buttons',
  'scope.monitor_from_me',
  'scope.monitor_direct',
  'scope.monitor_groups',
  'media.s3_path_style',
]
const ICON: Record<Tab, LucideIcon> = {
  Providers: KeyRound,
  Classification: Brain,
  Scope: Eye,
  Retention: RotateCcw,
  Schedules: CalendarClock,
  Audit: ScrollText,
  Media: HardDrive,
  Database: Database,
  Users: User,
  Notifications: Mail,
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
        placeholder={
          isSet ? translate('•••••••• (saved, leave blank to keep)') : translate('Not set')
        }
        onChange={(e) => onChange(e.target.value)}
      />
      {isSet && (
        <ConfirmDialog
          trigger={<Button variant="outline">{translate('Clear')}</Button>}
          title={translate('Remove the saved key?')}
          description={translate(
            'Iris stops using it until you enter a new one. Checks that need it will fail in the meantime.',
          )}
          confirmLabel={translate('Remove key')}
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
      toast.success('Kept media is being deleted.')
      return qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not delete the media.'),
  })
  const files = stats.data?.media_files ?? 0
  if (files === 0) return null
  return (
    <Section
      title={translate('Kept now')}
      description={translate(
        'Files stay until their keep time ends, even if you turn keeping off.',
      )}
    >
      <p className="text-sm">
        <span className="tabular font-medium">{files}</span>{' '}
        {files === 1 ? translate('file') : translate('files')},{' '}
        {fileSize(stats.data?.media_bytes ?? 0)}
      </p>
      <ConfirmDialog
        trigger={
          <Button variant="outline" className="w-fit" disabled={remove.isPending}>
            <Trash2 /> {translate('Delete all kept media')}
          </Button>
        }
        title={translate('Delete all kept media?')}
        description={translate(
          'Every kept photo and voice note is deleted from the storage. The messages and alerts stay.',
        )}
        confirmLabel={translate('Delete media')}
        onConfirm={() => remove.mutate()}
      />
    </Section>
  )
}

function TestButton({
  target,
  body,
  label = 'Test',
  disabled = false,
}: {
  label?: string
  disabled?: boolean
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
      <Button variant="outline" onClick={() => test.mutate()} disabled={disabled || test.isPending}>
        {test.isPending && <Loader2 className="animate-spin" />}{' '}
        {test.isPending ? translate('Testing') : translate(label)}
      </Button>
      {test.data && (
        <span
          role="status"
          className={`flex items-center gap-1.5 text-sm ${test.data.ok ? 'text-success' : 'text-danger'}`}
        >
          {test.data.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
          {translate(test.data.detail)}
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
        <span className="font-medium">{translate(label)}</span>
        {hint && <span className="text-muted-foreground">{translate(hint)}</span>}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={translate(label)} />
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
        <span>{translate('Category')}</span>
        <span>{translate('Needs a look from')}</span>
        <span>{translate('Harmful from')}</span>
      </div>
      <ul className="flex flex-col divide-y">
        {data.map((r) => (
          <li
            key={r.category}
            className="grid grid-cols-2 items-center gap-x-3 gap-y-1.5 py-2.5 sm:grid-cols-[1fr_7rem_7rem]"
          >
            <span className="col-span-2 text-sm font-medium sm:col-span-1">
              {translate(r.category)}
            </span>
            {(['low', 'high'] as const).map((f) => (
              <Input
                key={f}
                className="tabular"
                type="number"
                step="0.01"
                min={0}
                max={1}
                aria-label={`${translate(r.category)} ${f}`}
                value={edits[r.category]?.[f] ?? String(r[f])}
                onChange={(e) => onEdit(r.category, f, e.target.value)}
              />
            ))}
          </li>
        ))}
      </ul>
      <Button variant="outline" className="self-start" onClick={onReset}>
        <RotateCcw /> {translate('Reset all to defaults')}
      </Button>
      <p className="max-w-prose text-sm text-muted-foreground">
        {translate(
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
  const showByDefault = useShowContentByDefault()
  return (
    <>
      <Section
        title={translate('On this browser')}
        description={translate(
          'Stored content (message text, alert quotes, kept photos and voice notes) is hidden until you press the eye. This applies to this browser only.',
        )}
      >
        <Toggle
          label={translate('Show content by default')}
          hint={translate(
            'Everything starts shown, and you can still hide it with the eye. Leave it off on a shared screen.',
          )}
          checked={showByDefault}
          onChange={setShowContentByDefault}
        />
      </Section>
      <Section
        title={translate('Change password')}
        description={translate(
          'Use at least 8 characters. Changing it signs out every other browser.',
        )}
      >
        <form onSubmit={submit} className="flex max-w-sm flex-col gap-4">
          <Field label={translate('Current password')}>
            <Input
              type="password"
              autoComplete="current-password"
              value={form.current}
              onChange={(e) => setForm({ ...form, current: e.target.value })}
            />
          </Field>
          <Field label={translate('New password (at least 8 characters)')}>
            <Input
              type="password"
              autoComplete="new-password"
              value={form.next}
              onChange={(e) => setForm({ ...form, next: e.target.value })}
            />
          </Field>
          <Field label={translate('Repeat new password')}>
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
            {translate('Change password')}
          </Button>
        </form>
      </Section>
    </>
  )
}

export function Settings() {
  const { dir } = useLanguage()
  const qc = useQueryClient()
  const recoverOpenWA = useMutation({
    mutationFn: () => api('/api/schedules/openwa_recovery/run', { method: 'POST' }),
    onSuccess: () => {
      toast.success('OpenWA catch-up queued. See Schedules for results.')
      void qc.invalidateQueries({ queryKey: ['schedules'] })
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not queue catch-up.'),
  })
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
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  useEffect(() => {
    if (
      !['#parent-alert-recipients', '#alert-providers', '#provider-health'].includes(location.hash)
    )
      return
    const focus = () => {
      const target = document.getElementById(location.hash.slice(1))
      if (!target) return false
      target.scrollIntoView({ block: 'start' })
      target.focus({ preventScroll: true })
      return true
    }
    if (focus()) return
    const observer = new MutationObserver(() => {
      if (focus()) observer.disconnect()
    })
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [location.hash, location.search])
  const requestedTab =
    searchParams.get('tab') === 'Alerts' ? 'Notifications' : searchParams.get('tab')
  const tab: Tab = TABS.find((t) => t === requestedTab) ?? 'Providers'
  const setTab = (value: Tab) =>
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('tab', value)
      return next
    })
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [thresholdEdits, setThresholdEdits] = useState<
    Record<string, { low: string; high: string }>
  >({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  if (isError)
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title={translate('Settings')} />
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
    setSaveError('')
    try {
      await api('/api/settings', { method: 'PUT', body: JSON.stringify({ settings: changes }) })
      // Only the saved keys leave the draft: other unsaved edits survive (e.g. after "Clear").
      setEdit((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !clearKeys.includes(k))))
      if ('classification.thresholds' in changes) setThresholdEdits({})
      await qc.invalidateQueries()
      toast.success('Settings saved.')
    } catch (e) {
      setSaveError(
        e instanceof ApiError
          ? translate('Not saved: {value0}', { value0: e.message })
          : 'Not saved. Check your connection and try again.',
      )
      await qc.invalidateQueries({ queryKey: ['stats'] })
      await qc.invalidateQueries({ queryKey: ['alert-readiness'] })
      toast.error(
        e instanceof ApiError
          ? translate('Not saved: {value0}', { value0: e.message })
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
          toast.error(
            translate('Enter a number for "{value0}".', { value0: NUMBER_LABELS[k] ?? k }),
          )
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
        title={translate('Settings')}
        description={translate(
          'Providers, how Iris judges messages, where alerts go, and how long things are kept.',
        )}
      />
      <Link to="/setup" className="text-sm text-primary underline">
        {translate('Open setup checklist')}
      </Link>
      {saveError && (
        <p role="alert" className="text-sm text-danger">
          {translate(saveError)}
        </p>
      )}
      <Tabs
        dir={dir}
        value={tab}
        onValueChange={(v) => setTab(v as Tab)}
        orientation="vertical"
        className="flex flex-col gap-5 md:flex-row md:items-start"
      >
        <TabsList
          aria-label={translate('Settings sections')}
          className="-mx-4 px-4 md:mx-0 md:w-52 md:shrink-0 md:flex-col md:px-0"
        >
          {TABS.map((t) => {
            const Icon = ICON[t]
            return (
              <TabsTrigger key={t} value={t} className="md:justify-start">
                <span className="flex items-center gap-2">
                  <Icon className="size-4" /> {translate(t)}
                </span>
              </TabsTrigger>
            )
          })}
        </TabsList>

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <TabsContent value="Providers" className="flex flex-col gap-5">
            <Tabs
              value={
                searchParams.get('provider') === 'notifications' ||
                (!searchParams.has('provider') && location.hash === '#alert-providers')
                  ? 'notifications'
                  : 'ai'
              }
              onValueChange={(value) =>
                setSearchParams((current) => {
                  const next = new URLSearchParams(current)
                  next.set('tab', 'Providers')
                  next.set('provider', value)
                  return next
                })
              }
            >
              <TabsList aria-label={translate('Provider groups')} className="mb-5">
                <TabsTrigger value="ai">{translate('AI providers')}</TabsTrigger>
                <TabsTrigger value="notifications">
                  {translate('Notification providers')}
                </TabsTrigger>
              </TabsList>
              <TabsContent value="ai" className="flex flex-col gap-5">
                <Section
                  title={translate('Classification provider')}
                  description={translate(
                    'Choose how Iris classifies messages. Saved choices override server environment defaults.',
                  )}
                >
                  <Field label={translate('Classification provider')}>
                    <Select
                      value={classifier}
                      onChange={(e) => set('runtime.classification_provider')(e.target.value)}
                    >
                      <option value="openai">OpenAI</option>
                      <option value="ollama">{translate('Ollama (local)')}</option>
                    </Select>
                  </Field>
                </Section>
                {classifier === 'ollama' ? (
                  <Section
                    title="Ollama"
                    description={translate(
                      'Local text and image classifier. Detect installed models, test your choice, then save to use it for new jobs.',
                    )}
                  >
                    <Field label={translate('Ollama endpoint')}>
                      <Input
                        value={get('runtime.ollama_base_url')}
                        onChange={(e) => set('runtime.ollama_base_url')(e.target.value)}
                        placeholder="http://localhost:11434"
                      />
                    </Field>
                    <OllamaModelPicker
                      endpoint={get('runtime.ollama_base_url')}
                      value={
                        get('runtime.ollama_model') || data.local_providers?.ollama_model || ''
                      }
                      onChange={set('runtime.ollama_model')}
                    />
                    <p className="text-sm text-muted-foreground">
                      {translate(
                        'Local scores require calibration. Images and stickers are checked with their captions when the selected Ollama model supports vision. Missing media or failed checks still require review. Test Ollama checks text classification only.',
                      )}
                    </p>
                    <TestButton
                      target="ollama"
                      body={{
                        base_url: get('runtime.ollama_base_url'),
                        model: get('runtime.ollama_model') || data.local_providers?.ollama_model,
                      }}
                      label={translate('Test Ollama')}
                    />
                    <TestButton
                      target="ollama_image"
                      body={{
                        base_url: get('runtime.ollama_base_url'),
                        model: get('runtime.ollama_model') || data.local_providers?.ollama_model,
                      }}
                      label={translate('Test Ollama image')}
                    />
                  </Section>
                ) : (
                  <Section
                    title="OpenAI"
                    description={translate(
                      'Checks every message for harm. The moderation endpoint is free.',
                    )}
                  >
                    <Field label={translate('API key')}>
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
                  title={translate('Transcription provider')}
                  description={translate(
                    'Choose local transcription, OpenAI, or Cloudflare. No automatic cloud fallback is used.',
                  )}
                >
                  <Field label={translate('Provider')}>
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
                      <option value="local_whisper">
                        {translate('Mila companion / local Whisper')}
                      </option>
                    </Select>
                  </Field>
                </Section>
                {provider === 'local_whisper' ? (
                  <Section
                    title={translate('Mila companion / local Whisper')}
                    description={translate(
                      'Active local transcription API. The Mila desktop app itself does not provide this API.',
                    )}
                  >
                    <Field label={translate('Transcription endpoint')}>
                      <Input
                        value={get('runtime.whisper_url')}
                        onChange={(e) => set('runtime.whisper_url')(e.target.value)}
                        placeholder="http://mac.example:8081/v1/audio/transcriptions"
                      />
                    </Field>
                    <Field label={translate('Local transcription model')}>
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
                    <Field label={translate('Local transcription API key')}>
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
                      label={translate('Use environment API key when no saved key exists')}
                      checked={get('runtime.whisper_use_environment_key') !== 'false'}
                      onChange={(value) =>
                        set('runtime.whisper_use_environment_key')(String(value))
                      }
                    />
                    <Field label={translate('Fallback model (optional)')}>
                      <Input
                        value={get('runtime.whisper_fallback_model')}
                        onChange={(e) => set('runtime.whisper_fallback_model')(e.target.value)}
                      />
                    </Field>
                    <p className="text-sm text-muted-foreground">
                      {translate(
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
                      label={translate('Test transcription connection')}
                    />
                  </Section>
                ) : (
                  <Section
                    title={translate('Voice and video')}
                    description={translate(
                      'Turns audio into text so it can be checked like any message.',
                    )}
                  >
                    {provider === 'openai' ? (
                      <Field label={translate('OpenAI model')}>
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
                        <Field label={translate('Cloudflare account ID')}>
                          <Input
                            dir="ltr"
                            value={get('transcription.cloudflare_account_id')}
                            onChange={(e) =>
                              set('transcription.cloudflare_account_id')(e.target.value)
                            }
                          />
                        </Field>
                        <Field label={translate('Cloudflare API token')}>
                          <SecretInput
                            value={get('transcription.cloudflare_api_token')}
                            isSet={data['transcription.cloudflare_api_token'].set}
                            onChange={set('transcription.cloudflare_api_token')}
                            onClear={() =>
                              void save({ 'transcription.cloudflare_api_token': null })
                            }
                          />
                        </Field>
                        <Field label={translate('Model')}>
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
              <TabsContent value="notifications">
                <SectionGroup>
                  <div id="alert-providers" tabIndex={-1} className="scroll-mt-6 border-t pt-5">
                    <h2 className="text-xl font-semibold">{translate('Alert providers')}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {translate(
                        'Connect your sending services here. Choose recipients and their channels in Notifications.',
                      )}
                    </p>
                    <Button asChild variant="outline" className="mt-3">
                      <Link to="/settings?tab=Notifications">
                        {translate('Manage parent alerts')}
                      </Link>
                    </Button>
                  </div>
                  <Section
                    collapsible
                    defaultOpen
                    title={translate('Telegram connection')}
                    description={translate(
                      'Connect a bot, then choose Telegram and a chat ID for each parent.',
                    )}
                  >
                    {
                      <Field
                        label={translate('Telegram bot token')}
                        hint={translate(
                          'Create a bot through BotFather, start a conversation with it, and enter each parent’s chat ID in Notifications.',
                        )}
                      >
                        <SecretInput
                          value={get('alerts.telegram_bot_token')}
                          isSet={data['alerts.telegram_bot_token']?.set ?? false}
                          onChange={set('alerts.telegram_bot_token')}
                          onClear={() => void save({ 'alerts.telegram_bot_token': null })}
                        />
                      </Field>
                    }
                    <Button
                      variant="primary"
                      onClick={() =>
                        void save({ 'alerts.telegram_bot_token': get('alerts.telegram_bot_token') })
                      }
                      disabled={
                        saving ||
                        edit['alerts.telegram_bot_token'] === undefined ||
                        !get('alerts.telegram_bot_token').trim()
                      }
                    >
                      {translate('Save Telegram connection')}
                    </Button>
                    <TestButton
                      target="telegram"
                      body={{}}
                      label="Test Telegram connection"
                      disabled={
                        saving ||
                        !data['alerts.telegram_bot_token']?.set ||
                        edit['alerts.telegram_bot_token'] !== undefined
                      }
                    />
                    <p className="text-sm text-muted-foreground">
                      {translate(
                        !data['alerts.telegram_bot_token']?.set ||
                          edit['alerts.telegram_bot_token'] !== undefined
                          ? 'Save the Telegram bot token before testing.'
                          : 'The connection test checks the bot. No phone number is required. Sending messages requires a recipient chat ID in Notifications.',
                      )}
                    </p>
                  </Section>
                  <Section
                    collapsible
                    title="OpenWA"
                    description={translate('Choose the connected phone that sends parent alerts.')}
                  >
                    {
                      <Field label={translate('OpenWA sender phone')}>
                        <Select
                          value={get('alerts.sender_instance_id')}
                          onChange={(e) => set('alerts.sender_instance_id')(e.target.value)}
                        >
                          <option value="">{translate('Not set')}</option>
                          {instances?.map((i) => (
                            <option key={i.id} value={i.id}>
                              {i.kid_name}
                            </option>
                          ))}
                        </Select>
                      </Field>
                    }
                    <Button
                      variant="primary"
                      onClick={() =>
                        void save({
                          'alerts.sender_instance_id': get('alerts.sender_instance_id')
                            ? Number(get('alerts.sender_instance_id'))
                            : null,
                        })
                      }
                      disabled={saving || edit['alerts.sender_instance_id'] === undefined}
                    >
                      {translate('Save sender')}
                    </Button>
                    <ParentConnections showRecipients={false} />
                  </Section>
                  <NotificationsSettings />
                </SectionGroup>
              </TabsContent>
            </Tabs>
            <div id="provider-health" tabIndex={-1} className="scroll-mt-6">
              <Section
                collapsible
                defaultOpen={searchParams.get('section') === 'monitor'}
                title={translate('Provider monitoring')}
              >
                <ProviderHealth />
                {num(
                  'alerts.provider_notification_minutes',
                  'Provider alert interval (minutes)',
                  60,
                  10080,
                )}
                <p className="text-sm text-muted-foreground">
                  {translate(
                    'Down and recovery alerts are limited to one per provider per interval, with a minimum of one hour. Check frequency is configured in Schedules.',
                  )}
                </p>
                <Button asChild variant="outline">
                  <Link to="/settings?tab=Notifications&section=system">
                    {translate('Configure system notifications')}
                  </Link>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/settings?tab=Schedules">{translate('Configure check frequency')}</Link>
                </Button>
              </Section>
            </div>
          </TabsContent>

          <TabsContent value="Classification" className="flex flex-col gap-5">
            <Section
              title={translate('Processing mode')}
              description={translate(
                'Safety mode keeps unexamined media for review. Worker changes apply to new jobs; in-flight jobs finish.',
              )}
            >
              <Toggle
                label={translate('Local safety mode')}
                checked={get('runtime.local_safety_mode') === 'true'}
                onChange={(value) => set('runtime.local_safety_mode')(String(value))}
              />
              <Toggle
                label={translate('Require signed webhooks')}
                checked={get('runtime.require_webhook_signatures') === 'true'}
                onChange={(value) => set('runtime.require_webhook_signatures')(String(value))}
              />
              {num('runtime.workers', 'Classification workers (0 pauses processing)', 0, 16)}
              {num('runtime.delivery_workers', 'Dedicated alert workers', 0, 4)}
              {num('runtime.job_heartbeat_seconds', 'Job heartbeat seconds (0 disables)', 0, 120)}
              {num(
                'runtime.monitoring_silence_minutes',
                'Monitoring silence minutes (0 disables)',
                0,
                10080,
              )}
            </Section>
            <Section
              title={translate('Moderation')}
              description={translate(
                'How much of the chat Iris reads around a message it is unsure about.',
              )}
            >
              <Field label={translate('OpenAI moderation model')}>
                <Input
                  dir="ltr"
                  value={get('classification.model')}
                  onChange={(e) => set('classification.model')(e.target.value)}
                />
              </Field>
              {num('classification.context_window_size', 'Messages of context (1 to 20)', 1, 20)}
              {num('classification.context_max_age_hours', 'Context goes back (hours)', 1, 168)}
              <Field label={translate('Ollama learning from reviewed text')}>
                <Select
                  value={get('classification.learning_mode') || 'off'}
                  onChange={(e) => set('classification.learning_mode')(e.target.value)}
                >
                  <option value="off">{translate('Off')}</option>
                  <option value="shadow">
                    {translate('Shadow: compare without changing alerts')}
                  </option>
                  <option value="active">
                    {translate('Active: use examples to detect additional harm')}
                  </option>
                </Select>
              </Field>
              <p className="text-sm text-muted-foreground">
                {translate(
                  'Start with Shadow. Active keeps stronger baseline decisions and may add alerts or reviews. Applies to Ollama text messages; it does not train model weights.',
                )}
              </p>
              <Toggle
                label={translate('Use the public synthetic learning pack')}
                hint={translate(
                  'Versioned Hebrew and English guidance from GitHub. Private reviews remain local. Shadow compares results without changing alerts.',
                )}
                checked={get('classification.community_learning') === 'true'}
                onChange={(value) => set('classification.community_learning')(String(value))}
              />
              <Field label={translate('Find reviewed examples by')}>
                <Select
                  value={get('classification.learning_retrieval') || 'lexical'}
                  onChange={(e) => set('classification.learning_retrieval')(e.target.value)}
                >
                  <option value="lexical">{translate('Matching words')}</option>
                  <option value="semantic">{translate('Meaning (local embeddings)')}</option>
                </Select>
              </Field>
              {get('classification.learning_retrieval') === 'semantic' && (
                <>
                  <Field label={translate('Installed Ollama embedding model')}>
                    <Input
                      dir="ltr"
                      value={get('classification.learning_embedding_model')}
                      onChange={(e) =>
                        set('classification.learning_embedding_model')(e.target.value)
                      }
                    />
                  </Field>
                  <Field label={translate('Minimum semantic similarity (0 to 1)')}>
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={
                        edit['classification.learning_min_similarity'] ??
                        (get('classification.learning_min_similarity') || '0.7')
                      }
                      onChange={(e) =>
                        set('classification.learning_min_similarity')(e.target.value)
                      }
                    />
                  </Field>
                  <TestButton
                    target="ollama_embedding"
                    label={translate('Test embedding model')}
                    body={{
                      base_url: get('runtime.ollama_base_url'),
                      model: get('classification.learning_embedding_model'),
                    }}
                  />
                  <p className="text-sm text-muted-foreground">
                    {translate(
                      'Use an installed multilingual embedding model. If it is unavailable, Iris falls back to matching words. The similarity cutoff depends on the model; compare results in Shadow before using Active.',
                    )}
                  </p>
                </>
              )}
            </Section>
            <LearningSettings />
            <Section
              title={translate('Thresholds')}
              description={translate('Scores are 0 to 1. Lower numbers make Iris more cautious.')}
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

          <TabsContent value="Notifications" className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-surface p-4">
              <p className="max-w-prose text-sm text-muted-foreground">
                {translate(
                  'Sending connections are configured in Providers: SMTP, Telegram, OpenWA and GreenAPI.',
                )}
              </p>
              <Button asChild variant="outline">
                <Link to="/settings?tab=Providers&provider=notifications#alert-providers">
                  {translate('Configure alert providers')}
                </Link>
              </Button>
            </div>
            <SectionGroup key={searchParams.get('section') ?? 'parents'}>
              <Section
                collapsible
                defaultOpen={!searchParams.has('section')}
                title={translate('Parent alert delivery')}
                description={translate(
                  'Choose who receives alerts and select a channel for each parent. The default channel is used only for parents without their own selection.',
                )}
              >
                <ParentConnections showSender={false} />
                <details className="rounded-lg border p-3">
                  <summary className="cursor-pointer text-sm font-medium">
                    {translate('Default channel and delivery status')}
                  </summary>
                  <div className="mt-4 flex flex-col gap-4">
                    <ChoiceCards
                      label={translate('Default alert channel')}
                      value={get('alerts.channel') || 'openwa'}
                      onChange={set('alerts.channel')}
                      options={[
                        { value: 'openwa', label: translate('WhatsApp via OpenWA') },
                        { value: 'greenapi', label: translate('WhatsApp via GreenAPI') },
                        { value: 'smtp', label: translate('Email via SMTP') },
                        { value: 'telegram', label: translate('Telegram bot') },
                      ]}
                    />
                    <AlertDeliveryHealth />
                  </div>
                </details>
                <TestButton
                  target="alert"
                  label={translate('Test parent alert delivery')}
                  disabled={edit['alerts.channel'] !== undefined}
                  body={{
                    sender_instance_id: get('alerts.sender_instance_id') || undefined,
                    recipient: get('alerts.recipient') || undefined,
                  }}
                />
                {edit['alerts.channel'] !== undefined && (
                  <p role="status" className="text-sm text-muted-foreground">
                    {translate('Save changes to apply this channel before testing alert delivery.')}
                  </p>
                )}
              </Section>
              <Section
                collapsible
                defaultOpen={searchParams.get('section') === 'system'}
                title={translate('System notifications')}
              >
                <SystemNotifications settings={data as unknown as Record<string, unknown>} />
              </Section>
              <Section
                collapsible
                defaultOpen={searchParams.get('section') === 'timing'}
                title={translate('Frequency and timing')}
              >
                <ChoiceCards
                  label={translate('Parent notification design')}
                  value={get('alerts.notification_style') || 'summary'}
                  onChange={set('alerts.notification_style')}
                  options={[
                    { value: 'summary', label: translate('Private summary (recommended)') },
                    { value: 'detailed', label: translate('Message preview') },
                  ]}
                />
                <div
                  className="max-w-sm rounded-3xl border bg-surface-2/50 p-4"
                  aria-label={translate('Notification preview')}
                >
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                    <Mail className="size-4" />
                    {translate('Iris · Family update')}
                  </div>
                  <div className="rounded-2xl rounded-ss-sm bg-success-soft/60 p-4 text-sm font-normal leading-relaxed">
                    <p className="mb-3 font-medium">{translate('A message to check together')}</p>
                    <p>
                      {translate('Child: Alex')}
                      <br />
                      {translate('Chat: School friends')}
                      <br />
                      {translate('Time: 16:30')}
                    </p>
                    <p className="my-3">
                      {get('alerts.notification_style') === 'detailed'
                        ? translate('💬 “Example message shown here.”')
                        : translate(
                            'Iris flagged a possible concern. Open Iris to see the conversation.',
                          )}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {translate('Sent by Iris · Server: your Iris address')}
                    </p>
                  </div>
                  {get('alerts.review_buttons') === 'true' && (
                    <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs text-primary">
                      <span className="rounded-lg border bg-surface p-2">{translate('SAFE')}</span>
                      <span className="rounded-lg border bg-surface p-2">
                        {translate('Harmful')}
                      </span>
                      <span className="rounded-lg border bg-surface p-2">
                        {translate('Ignore')}
                      </span>
                    </div>
                  )}
                  <p className="mt-2 text-xs text-muted-foreground">
                    {translate(
                      'Example preview. Your phone app controls its fonts and appearance.',
                    )}
                  </p>
                </div>
                <p className="text-sm text-muted-foreground">
                  {translate(
                    'A persistent queue spaces sends across all chats and recipients. Resends and follow-ups share these limits. Excess messages wait; these limits do not guarantee protection from WhatsApp account restrictions.',
                  )}
                </p>
                {num(
                  'alerts.send_interval_seconds',
                  'Minimum interval between sends (seconds)',
                  5,
                  3600,
                )}
                {num('alerts.send_hourly_limit', 'Maximum sends per sender per hour', 1, 1000)}
                {num('alerts.send_daily_limit', 'Maximum sends per sender per 24 hours', 1, 10000)}
                {num('alerts.cooldown_minutes', 'Cooldown per chat (minutes)', 0, 1440)}
                <Field label={translate('Time zone')}>
                  <Input
                    dir="ltr"
                    value={get('alerts.timezone')}
                    onChange={(e) => set('alerts.timezone')(e.target.value)}
                  />
                </Field>
                {bool(
                  'alerts.alert_on_review',
                  'Also alert on items needing review',
                  'When enabled, new review items can notify parents. Existing backlog stays in Review; send individual items explicitly.',
                )}
                {bool(
                  'alerts.notify_changes',
                  'Tell me when an alerted message is edited or deleted',
                  'Sends a short follow-up using the selected alert channel. It never repeats the message.',
                )}
              </Section>
              <Section
                collapsible
                defaultOpen={searchParams.get('section') === 'review'}
                title={translate('Review from your phone')}
                description={translate(
                  'GreenAPI and Telegram can include SAFE, Harmful and Ignore buttons in message alerts.',
                )}
              >
                {bool(
                  'alerts.review_buttons',
                  'Add review buttons to alerts',
                  'The first valid parent response wins. Later choices are saved in notes. Personal chats only; buttons expire after four days.',
                )}
                <p className="text-sm text-muted-foreground">
                  {translate(
                    'Use a dedicated Telegram bot or GreenAPI notification instance with no webhook or other polling consumer. For GreenAPI, enable incoming message notifications. Iris checks responses in Settings → Schedules → Parent alert responses. GreenAPI buttons are a beta provider feature.',
                  )}
                </p>
              </Section>
              <Section
                collapsible
                defaultOpen={searchParams.get('section') === 'links'}
                title={translate('Iris links')}
                description={translate(
                  'Use the public domain parents can open. This URL prefixes alert and media links. The saved value overrides IRIS_PUBLIC_BASE_URL from .env / Docker Compose.',
                )}
              >
                <Field label={translate('Iris base URL')}>
                  <Input
                    type="url"
                    dir="ltr"
                    placeholder="https://iris.example.com"
                    value={get('runtime.public_base_url')}
                    onChange={(e) => set('runtime.public_base_url')(e.target.value)}
                  />
                </Field>
              </Section>
              <Section
                collapsible
                defaultOpen={searchParams.get('section') === 'webhooks'}
                title={translate('OpenWA webhooks')}
                description={translate(
                  'Address OpenWA uses to deliver messages to Iris. For a private deployment, use the reachable NAS URL permitted by OpenWA’s SSRF_ALLOWED_HOSTS. Leave blank to use the server default, or the public Iris URL if no server default is configured.',
                )}
              >
                <Field label={translate('OpenWA webhook base URL')}>
                  <Input
                    type="url"
                    dir="ltr"
                    placeholder="http://192.0.2.10:8182"
                    value={get('runtime.webhook_base_url')}
                    onChange={(e) => set('runtime.webhook_base_url')(e.target.value)}
                  />
                </Field>
                <Field label={translate('Webhook delivery attempts (1–5 total)')}>
                  <Input
                    type="number"
                    min={1}
                    max={5}
                    value={get('openwa.webhook_attempts')}
                    onChange={(e) => set('openwa.webhook_attempts')(e.target.value)}
                  />
                </Field>
                <Toggle
                  label={translate('Recover missed OpenWA messages automatically')}
                  checked={get('openwa.recovery_enabled') !== 'false'}
                  onChange={(value) => set('openwa.recovery_enabled')(String(value))}
                />
                <Field label={translate('Catch-up lookback (hours, 1–720)')}>
                  <Input
                    type="number"
                    min={1}
                    max={720}
                    value={get('openwa.recovery_hours')}
                    onChange={(e) => set('openwa.recovery_hours')(e.target.value)}
                  />
                </Field>
                <p className="text-sm text-muted-foreground">
                  {translate(
                    'Saved retry settings apply to existing Iris webhooks within a minute. Catch-up uses retained OpenWA messages, respects monitoring scope and retention, and avoids duplicates. Use Schedules → OpenWA message catch-up → Run now for manual recovery.',
                  )}
                </p>
                <Button
                  variant="outline"
                  disabled={
                    recoverOpenWA.isPending ||
                    saving ||
                    Object.keys(edit).some((key) => key.startsWith('openwa.'))
                  }
                  onClick={() => recoverOpenWA.mutate()}
                >
                  {translate('Recover missed messages now')}
                </Button>
              </Section>
            </SectionGroup>
          </TabsContent>

          <TabsContent value="Scope" className="flex flex-col gap-5">
            <Section
              title={translate('What to watch')}
              description={translate('Turn off anything you do not want Iris to check.')}
            >
              <div className="flex flex-col divide-y">
                {bool('scope.monitor_from_me', 'Messages the child sends')}
                {bool('scope.monitor_direct', 'Direct chats')}
                {bool('scope.monitor_groups', 'Groups')}
              </div>
            </Section>
          </TabsContent>

          <TabsContent value="Schedules" className="flex flex-col gap-5">
            <ScheduleSettings />
          </TabsContent>

          <TabsContent value="Retention" className="flex flex-col gap-5">
            <Section
              title={translate('Persistent media archiving')}
              description={translate(
                'Iris and OpenWA keep separate copies. A saved Iris copy is used first when viewing media.',
              )}
            >
              <Toggle
                label={translate('Keep checked media in Iris')}
                checked={mediaOn}
                onChange={(on) => set('media.policy')(on ? 'harmful_review' : 'off')}
                hint={translate(
                  'Uses the storage and content policy selected under Media. Withheld content is never kept; videos are viewed through OpenWA.',
                )}
              />
              <p className="text-sm">
                {translate('OpenWA archive:')}{' '}
                {data.provider_media?.archive_enabled == null
                  ? translate('Not reported')
                  : data.provider_media.archive_enabled
                    ? translate('Enabled')
                    : translate('Disabled')}
                {' · '}
                {translate('Sent media:')}{' '}
                {data.provider_media?.archive_outbound == null
                  ? translate('Not reported')
                  : data.provider_media.archive_outbound
                    ? translate('Archived')
                    : translate('Not archived')}
              </p>
              {data.provider_media?.archive_ttl_days != null && (
                <p className="text-sm text-muted-foreground">
                  {translate('OpenWA expiry:')}{' '}
                  {data.provider_media.archive_ttl_days === 0
                    ? translate('No automatic expiry')
                    : translate('{value0} days', { value0: data.provider_media.archive_ttl_days })}
                  {translate('. Download timeout:')}{' '}
                  {data.provider_media.download_timeout_seconds ?? translate('Not reported')}{' '}
                  {translate('seconds.')}
                </p>
              )}
              <p className="text-sm text-muted-foreground">
                {translate(
                  'OpenWA values are deployment settings. Change CHAT_MEDIA_ARCHIVE_ENABLED, CHAT_MEDIA_ARCHIVE_OUTBOUND and CHAT_MEDIA_ARCHIVE_TTL_DAYS in the OpenWA Portainer service, then redeploy. This OpenWA version has no archive settings API. Iris retention below does not delete OpenWA copies.',
                )}
              </p>
              {num('media.recovery_attempts', 'Media recovery attempts (0 disables)', 0, 3)}
              {num('media.recovery_wait_seconds', 'Wait before media recovery (seconds)', 0, 30)}
              <p className="text-sm text-muted-foreground">
                {translate(
                  'If OpenWA omitted a download, Iris asks WhatsApp again using at most ten recent messages and keeps only the requested file. Recovery is limited to 25 MB and may take up to 65 seconds per attempt. Expired WhatsApp media cannot always be recovered.',
                )}
              </p>
            </Section>
            <Section
              title={translate('How long to keep things')}
              description={translate(
                'Messages tied to an alert are kept until that alert expires. Kept media has its own limit under Media.',
              )}
            >
              {num('retention.message_days', 'Keep messages for (days)', 1)}
              {num('retention.message_hours', 'Message retention in hours (0 uses days)', 0, 87600)}
              <p className="text-sm text-muted-foreground">
                {translate(
                  'Cleanup runs hourly. Messages linked to retained alerts and unresolved review items remain available; OpenWA retention is managed separately.',
                )}
              </p>
              {num('retention.alert_days', 'Keep alerts for (days)', 1)}
              {num('media.retention_days', 'Keep media for (days)', 1)}
              {num('media.retention_hours', 'Media retention in hours (0 uses days)', 0, 87600)}
            </Section>
          </TabsContent>

          <TabsContent value="Audit">
            <AuditSettings />
          </TabsContent>

          <TabsContent value="Media" className="flex flex-col gap-5">
            <Section
              title={translate('Keep media')}
              description={translate(
                'By default Iris deletes every photo and voice note as soon as it has been checked. Turn this on to keep copies you can open from alerts.',
              )}
            >
              <Toggle
                label={translate('Keep media')}
                hint={translate('Files can only be opened after you sign in to Iris.')}
                checked={mediaOn}
                onChange={(on) => set('media.policy')(on ? 'harmful' : 'off')}
              />
              {mediaOn && (
                <fieldset className="flex flex-col gap-2">
                  <legend className="mb-1 text-sm font-medium">{translate('What to keep')}</legend>
                  {(
                    [
                      ['harmful', 'Only what Iris judges harmful', 'The media behind your alerts.'],
                      [
                        'harmful_review',
                        'Harmful and needs a look',
                        'Also the items waiting in the review queue.',
                      ],
                      ['all', 'Everything', 'Every photo and voice note. Uses the most space.'],
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
                        <span className="font-medium">{translate(label)}</span>
                        <span className="text-muted-foreground">{translate(hint)}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
              )}
              <p className="max-w-prose text-sm text-muted-foreground">
                {translate(
                  'Content Iris withholds (anything sexual involving minors, or sexual images) is never kept, whatever you choose. Videos are not kept at all, because Iris checks what a video says, not what it shows.',
                )}
              </p>
            </Section>
            <KeptMedia />

            {mediaOn && (
              <>
                <Section title={translate('Where to keep it')}>
                  <Field label={translate('Storage')} className="max-w-72">
                    <Select
                      value={get('media.backend')}
                      onChange={(e) => set('media.backend')(e.target.value)}
                    >
                      <option value="local">{translate("This server's disk")}</option>
                      <option value="s3">{translate('S3-compatible storage')}</option>
                    </Select>
                  </Field>
                  {get('media.backend') === 'local' ? (
                    <p className="max-w-prose text-sm text-muted-foreground">
                      {translate('Files go to the')} <code>media</code>{' '}
                      {translate(
                        "folder inside Iris's data folder, next to the database. In Docker that is the data volume.",
                      )}
                    </p>
                  ) : (
                    <>
                      <p className="max-w-prose text-sm text-muted-foreground">
                        {translate(
                          'Works with Cloudflare R2, AWS S3, SeaweedFS, MinIO and other S3-compatible services. Create the bucket first.',
                        )}
                      </p>
                      <Field
                        label={translate('Endpoint')}
                        hint={translate(
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
                        <Field label={translate('Bucket')}>
                          <Input
                            dir="ltr"
                            value={get('media.s3_bucket')}
                            onChange={(e) => set('media.s3_bucket')(e.target.value)}
                            autoComplete="off"
                          />
                        </Field>
                        <Field
                          label={translate('Region')}
                          hint={translate('Use auto for Cloudflare R2.')}
                        >
                          <Input
                            dir="ltr"
                            value={get('media.s3_region')}
                            onChange={(e) => set('media.s3_region')(e.target.value)}
                            autoComplete="off"
                          />
                        </Field>
                      </div>
                      <Field label={translate('Access key ID')}>
                        <Input
                          dir="ltr"
                          value={get('media.s3_access_key')}
                          onChange={(e) => set('media.s3_access_key')(e.target.value)}
                          autoComplete="off"
                        />
                      </Field>
                      <Field label={translate('Secret access key')}>
                        <SecretInput
                          value={get('media.s3_secret_key')}
                          isSet={data['media.s3_secret_key'].set}
                          onChange={set('media.s3_secret_key')}
                          onClear={() => void save({ 'media.s3_secret_key': null })}
                        />
                      </Field>
                      <Field
                        label={translate('Folder in the bucket')}
                        hint={translate('Optional. Everything is kept under it.')}
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
                        'Path-style addresses',
                        'Keep this on for R2, SeaweedFS and MinIO. Turn it off for AWS S3 buckets that need bucket.host addresses.',
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
                    label={translate('Test storage')}
                  />
                </Section>

                <Section title={translate('How long to keep it')}>
                  <p className="max-w-prose text-sm text-muted-foreground">
                    {translate(
                      'Configure media, message and alert retention in Settings → Retention.',
                    )}
                  </p>
                </Section>
              </>
            )}
          </TabsContent>

          <TabsContent value="Database">
            <DatabaseTab />
          </TabsContent>

          <TabsContent value="Users" className="flex flex-col gap-6">
            <UserSettings />
            <Account />
          </TabsContent>

          {dirty && tab !== 'Users' && tab !== 'Database' && (
            <div className="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-surface p-3 shadow-overlay md:bottom-4">
              <p className="text-sm text-muted-foreground">
                {translate('You have unsaved changes.')}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setEdit({})
                    setThresholdEdits({})
                  }}
                >
                  {translate('Discard')}
                </Button>
                <Button variant="primary" onClick={saveAll} disabled={saving}>
                  {saving && <Loader2 className="animate-spin" />} {translate('Save')}
                </Button>
              </div>
            </div>
          )}
        </div>
      </Tabs>
    </div>
  )
}
