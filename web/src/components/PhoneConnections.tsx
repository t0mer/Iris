import { RepairPhone } from './RepairPhone'
import { EditPhone } from './EditPhone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Link2, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { KidAvatar } from './KidAvatar'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { ConfirmDialog, Dialog, DialogContent, DialogTrigger } from './ui/dialog'
import { Field, Input, Select } from './ui/field'
import { Switch } from './ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { Instance } from '../lib/types'
import { PhonePairing, type PairingState } from './PhonePairing'

const fail = (fallback: string) => (e: unknown) =>
  toast.error(e instanceof ApiError ? e.message : fallback)

export function PhoneCard({
  i,
  senderConnection = false,
}: {
  i: Instance
  senderConnection?: boolean
}) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['instances'] })
  const [repairOpen, setRepairOpen] = useState(false)
  const checkSession = useMutation({
    mutationFn: () => api<Instance>(`/api/instances/${i.id}/check-session`, { method: 'POST' }),
    onSuccess: (phone) => {
      if (['qr_ready', 'action_required'].includes(phone.connection_status || ''))
        setRepairOpen(true)
      void qc.invalidateQueries({ queryKey: ['stats'] })
      return refresh()
    },
    onError: fail('Could not check this session.'),
  })
  const register = useMutation({
    mutationFn: () => api(`/api/instances/${i.id}/register-webhook`, { method: 'POST' }),
    onSuccess: () => {
      toast.success(`Webhook registered in OpenWA for ${i.kid_name}.`)
      return refresh()
    },
    onError: (error) => {
      fail('Could not register the webhook.')(error)
      void refresh()
    },
  })
  const rotate = useMutation({
    mutationFn: () => api(`/api/instances/${i.id}/rotate-token`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('New webhook address created. Register it in OpenWA again.')
      return refresh()
    },
    onError: fail('Could not rotate the token.'),
  })
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api(`/api/instances/${i.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
    onSuccess: (_d, enabled) => {
      toast.success(enabled ? `Watching ${i.kid_name} again.` : `Paused watching ${i.kid_name}.`)
      return refresh()
    },
    onError: fail('Could not change this phone.'),
  })
  const changeRole = useMutation({
    mutationFn: (role: 'child' | 'parent') =>
      api(`/api/instances/${i.id}`, { method: 'PATCH', body: JSON.stringify({ role }) }),
    onSuccess: () => refresh(),
    onError: fail('Could not change the phone role.'),
  })
  const [deleteMessages, setDeleteMessages] = useState(false)
  const [deleteOpenWA, setDeleteOpenWA] = useState(false)
  const [removalStage, setRemovalStage] = useState(0)
  const [removalError, setRemovalError] = useState('')
  const remove = useMutation({
    mutationFn: async (alsoDelete: boolean) => {
      setRemovalError('')
      setRemovalStage(1)
      if (alsoDelete) {
        await api(`/api/instances/${i.id}/remove-openwa?stage=deactivate`, { method: 'POST' })
        setRemovalStage(2)
        await api(`/api/instances/${i.id}/remove-openwa?stage=delete`, { method: 'POST' })
        setRemovalStage(3)
      }
      await api(
        `/api/instances/${i.id}${deleteMessages && !parent ? '?delete_messages=true' : ''}`,
        {
          method: 'DELETE',
        },
      )
      setRemovalStage(4)
    },
    onSuccess: () => {
      toast.success(`${i.kid_name} removed.`)
      void qc.invalidateQueries({ queryKey: ['stats'] })
      return refresh()
    },
    onError: (error) =>
      setRemovalError(error instanceof Error ? error.message : 'Could not remove this phone.'),
  })
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(i.webhook_url)
      toast.success('Webhook address copied.')
    } catch {
      toast.error('Could not copy. Select the address and copy it by hand.')
    }
  }
  const parent = senderConnection || i.role === 'parent'
  return (
    <li className="flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-3">
        <KidAvatar name={i.kid_name} className="size-10 text-base" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-lg font-semibold">{i.kid_name}</span>
          <span className="truncate text-sm text-muted-foreground">
            {i.openwa_base_url}, session {i.session_name || i.openwa_instance_id.slice(0, 8)}
          </span>
        </div>
        {!parent && (
          <label className="flex items-center gap-2 text-sm font-medium">
            {i.enabled ? 'Watching enabled' : 'Paused'}
            <Switch
              checked={i.enabled}
              onCheckedChange={(v) => toggle.mutate(v)}
              aria-label={`Watch ${i.kid_name}`}
            />
          </label>
        )}
        {parent && <Badge tone="neutral">Parent connection</Badge>}
        <EditPhone phone={i} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          tone={
            i.connection_status === 'ready'
              ? 'success'
              : !i.connection_status || i.connection_status === 'unknown'
                ? 'neutral'
                : 'danger'
          }
        >
          {i.connection_status === 'ready'
            ? 'WhatsApp connected'
            : i.connection_status === 'qr_ready' || i.connection_status === 'action_required'
              ? 'WhatsApp needs re-pairing'
              : i.connection_status === 'disconnected'
                ? 'WhatsApp disconnected'
                : i.connection_status === 'initializing' || i.connection_status === 'authenticating'
                  ? 'WhatsApp connecting'
                  : i.connection_status === 'unreachable'
                    ? 'OpenWA unreachable'
                    : i.connection_status === 'missing'
                      ? 'OpenWA session missing'
                      : i.connection_status === 'failed'
                        ? 'WhatsApp connection failed'
                        : 'Connection not checked'}
        </Badge>
        {i.connection_checked_at && (
          <span className="text-xs text-muted-foreground">
            Checked {relativeTime(i.connection_checked_at)}
          </span>
        )}
        <Button
          variant="outline"
          onClick={() => checkSession.mutate()}
          disabled={checkSession.isPending}
        >
          {checkSession.isPending ? 'Checking…' : 'Check connection'}
        </Button>
      </div>
      {i.enabled &&
        i.connection_status &&
        !['ready', 'unknown', 'initializing', 'authenticating'].includes(i.connection_status) && (
          <p role="alert" className="text-sm text-danger">
            Monitoring is enabled, but this phone is not connected. New messages cannot be checked
            until WhatsApp reconnects.
          </p>
        )}
      {!parent && i.enabled && (
        <div className="space-y-2">
          <Badge tone={i.monitoring_status === 'failed' ? 'danger' : 'neutral'}>
            {i.monitoring_status === 'failed'
              ? 'Monitoring setup failed'
              : i.monitoring_status === 'registered'
                ? 'Monitoring webhook registered'
                : 'Monitoring setup not verified'}
          </Badge>
          {i.monitoring_error && (
            <p role="alert" className="text-sm text-danger">
              {i.monitoring_error} Retry Register webhook below.
            </p>
          )}
        </div>
      )}
      <RepairPhone phone={i} open={repairOpen} onOpenChange={setRepairOpen} />
      <Field label={`Role for ${i.kid_name}`}>
        <Select
          value={i.role || 'child'}
          onChange={(event) => changeRole.mutate(event.target.value as 'child' | 'parent')}
        >
          <option value="child">Child — monitored when watching is enabled</option>
          <option value="parent">Parent — alert delivery only</option>
        </Select>
      </Field>
      {!parent && (
        <>
          <p className="text-sm">
            {i.last_webhook_at ? (
              <>
                Last message received <strong>{relativeTime(i.last_webhook_at)}</strong>.
              </>
            ) : (
              <Badge tone="warning">Nothing received yet</Badge>
            )}
            {!i.last_webhook_at && (
              <span className="ms-2 text-muted-foreground">
                Register the webhook below, then send a test message.
              </span>
            )}
          </p>
          <div className="flex flex-col gap-1.5">
            <span aria-hidden className="text-sm font-medium">
              Webhook address
            </span>
            <div className="flex items-stretch gap-2">
              <Input
                readOnly
                dir="ltr"
                aria-label="Webhook address"
                value={i.webhook_url}
                onFocus={(e) => e.currentTarget.select()}
                className="min-w-0 flex-1 font-mono text-xs"
              />
              <Button
                variant="outline"
                size="icon"
                aria-label="Copy webhook address"
                onClick={() => void copy()}
              >
                <Copy />
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              onClick={() => register.mutate()}
              disabled={register.isPending}
            >
              <Link2 /> Register in OpenWA
            </Button>
            <ConfirmDialog
              trigger={
                <Button variant="outline">
                  <RefreshCw /> New webhook address
                </Button>
              }
              title="Create a new webhook address?"
              description={`The current address stops working immediately. You must register the new one in OpenWA before ${i.kid_name}'s messages are checked again.`}
              confirmLabel="Create new address"
              tone="primary"
              onConfirm={() => rotate.mutate()}
            />
          </div>
        </>
      )}
      {parent && (
        <p className="text-sm">
          Used for alert delivery. This phone's messages are not monitored. Choose the alert sender
          in <Link to="/settings">Settings</Link>.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <ConfirmDialog
          trigger={
            <Button variant="danger-outline" className="ms-auto">
              <Trash2 /> Remove
            </Button>
          }
          title={`Remove ${i.kid_name}?`}
          description={
            parent
              ? 'This parent connection is removed. Select another sender in Settings if it is used for alert delivery.'
              : 'Iris stops watching this phone. Messages already saved stay until the retention window removes them.'
          }
          confirmLabel="Remove phone"
          onConfirm={() => remove.mutateAsync(deleteOpenWA)}
          pending={remove.isPending}
          keepOpen
          onOpenChange={(open) => {
            if (open) {
              setDeleteMessages(false)
              setDeleteOpenWA(false)
              setRemovalStage(0)
              setRemovalError('')
            }
          }}
        >
          <label className="flex min-h-11 items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1 size-5 shrink-0"
              checked={deleteOpenWA}
              disabled={remove.isPending}
              onChange={(e) => setDeleteOpenWA(e.target.checked)}
            />
            <span>
              Also delete the OpenWA session
              <span className="mt-1 block text-muted-foreground">
                Unlinks WhatsApp and deletes its saved session. Leave unchecked to remove only from
                Iris.
              </span>
            </span>
          </label>
          {!parent && (
            <label className="flex min-h-11 items-start gap-3 text-sm">
              <input
                type="checkbox"
                className="mt-1 size-5"
                checked={deleteMessages}
                disabled={remove.isPending}
                onChange={(e) => setDeleteMessages(e.target.checked)}
              />
              <span>
                Also delete saved received messages
                <span className="block text-muted-foreground">
                  Deletes received messages exclusive to this phone, including their alerts and
                  stored media. Sent and shared messages stay. This does not delete messages from
                  WhatsApp.
                </span>
              </span>
            </label>
          )}
          {removalStage > 0 && (
            <div className="flex flex-col gap-2" aria-live="polite">
              <progress
                aria-label="Phone removal progress"
                className="h-3 w-full"
                max={deleteOpenWA ? 3 : 1}
                value={deleteOpenWA ? Math.min(removalStage - 1, 3) : removalStage === 4 ? 1 : 0}
              />
              <p role="status">
                {removalStage === 4
                  ? 'Phone removed.'
                  : deleteOpenWA
                    ? [
                        '',
                        'Deactivating WhatsApp…',
                        'Deleting the OpenWA session…',
                        'Removing the Iris entry…',
                      ][removalStage]
                    : 'Removing the Iris entry…'}
              </p>
              {deleteOpenWA && (
                <ol className="text-sm text-muted-foreground">
                  <li>{removalStage > 1 ? '✓ ' : ''}Deactivate WhatsApp</li>
                  <li>{removalStage > 2 ? '✓ ' : ''}Delete OpenWA session</li>
                  <li>{removalStage > 3 ? '✓ ' : ''}Remove Iris entry</li>
                </ol>
              )}
            </div>
          )}
          {removalError && (
            <p role="alert" className="text-sm text-danger">
              {removalError} You can retry removal.
            </p>
          )}
        </ConfirmDialog>
      </div>
    </li>
  )
}

export function AddPhone({ defaultRole = 'child' }: { defaultRole?: 'child' | 'parent' }) {
  const qc = useQueryClient()
  const { data: pairingConfig } = useQuery({
    queryKey: ['pairing-config'],
    queryFn: () => api<{ configured: boolean }>('/api/pairing/config'),
  })
  const [open, setOpen] = useState(false)
  const [pairing, setPairing] = useState<PairingState | null>(null)
  const savedPairing = useRef<string | null>(null)
  const [mode, setMode] = useState('manual')
  const autoSaveToken = useRef<string | null>(null)
  const [savedPhone, setSavedPhone] = useState<Instance | null>(null)
  const [optionalName, setOptionalName] = useState('')
  const [form, setForm] = useState({
    role: defaultRole,
    kid_name: '',
    phone_number: '',
    openwa_base_url: '',
    openwa_instance_id: '',
    openwa_api_key: '',
  })
  const add = useMutation({
    mutationFn: () =>
      api<Instance>(pairing?.token ? `/api/pairing/${pairing.token}/complete` : '/api/instances', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          verify_openwa: mode === 'manual',
          openwa_instance_id: pairing?.session_id || form.openwa_instance_id,
          ...(mode === 'automatic' ? { kid_name: form.kid_name || pairing?.session_name } : {}),
          phone_number: form.phone_number || null,
        }),
      }),
    onSuccess: (phone) => {
      if (pairing?.token) {
        setSavedPhone(phone)
        setOptionalName('')
      }
      savedPairing.current = pairing?.token || null
      toast.success(
        form.role === 'parent'
          ? `${phone.kid_name} added as a parent connection.`
          : pairing?.token
            ? `${phone.kid_name} paired and registered.`
            : `${form.kid_name} added. Register the webhook to start watching.`,
      )
      setForm({
        role: defaultRole,
        kid_name: '',
        phone_number: '',
        openwa_base_url: '',
        openwa_instance_id: '',
        openwa_api_key: '',
      })
      setOpen(false)
      setPairing(null)
      return qc.invalidateQueries({ queryKey: ['instances'] })
    },
    onError: fail('Could not add the phone. Check the OpenWA address and try again.'),
  })
  const rename = useMutation({
    mutationFn: () =>
      api(`/api/instances/${savedPhone!.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ kid_name: optionalName.trim() }),
      }),
    onSuccess: () => {
      setSavedPhone(null)
      return qc.invalidateQueries({ queryKey: ['instances'] })
    },
    onError: fail('Could not save the name. The phone is already connected.'),
  })
  useEffect(() => {
    if (
      open &&
      mode === 'automatic' &&
      pairing?.status === 'ready' &&
      pairing.token &&
      autoSaveToken.current !== pairing.token
    ) {
      autoSaveToken.current = pairing.token
      add.mutate()
    }
  }, [open, mode, pairing?.status, pairing?.token, add])
  const f = (k: keyof typeof form) => ({
    value: form[k],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value }),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'automatic' && pairing?.status !== 'ready') return
    add.mutate()
  }
  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (add.isPending) return
          if (!value && pairing) {
            setForm((previous) => ({ ...previous, openwa_instance_id: '' }))
            setPairing(null)
          }
          setOpen(value)
        }}
      >
        <DialogTrigger asChild>
          <Button variant="primary">
            <Plus /> Add a phone
          </Button>
        </DialogTrigger>
        <DialogContent
          title="Add a phone"
          description={
            defaultRole === 'child'
              ? 'Add a child phone to monitor its messages.'
              : 'Add a WhatsApp sender connection for parent alerts. Sender messages are not monitored.'
          }
        >
          <Tabs
            value={mode}
            onValueChange={(value) => {
              if (add.isPending) return
              if (pairing) {
                setPairing(null)
                setForm((previous) => ({ ...previous, openwa_instance_id: '' }))
              }
              setMode(value)
            }}
          >
            <TabsList className="mb-4 grid grid-cols-2 gap-2">
              <TabsTrigger value="manual">Manual</TabsTrigger>
              {pairingConfig?.configured && <TabsTrigger value="automatic">Automatic</TabsTrigger>}
            </TabsList>
            <TabsContent value={mode}>
              <form onSubmit={submit} className="flex flex-col gap-4">
                {open && mode === 'automatic' && (
                  <PhonePairing name="" onChange={setPairing} savedToken={savedPairing} />
                )}
                {mode === 'manual' && (
                  <>
                    <Field label={form.role === 'parent' ? "Parent's name" : "Child's name"}>
                      <Input required={mode === 'manual'} {...f('kid_name')} />
                    </Field>
                    {mode === 'manual' && (
                      <>
                        <Field label="OpenWA address">
                          <Input
                            required
                            type="url"
                            dir="ltr"
                            placeholder="https://openwa.example.com"
                            {...f('openwa_base_url')}
                            disabled={Boolean(pairing)}
                          />
                        </Field>
                        <Field
                          label="OpenWA session ID"
                          hint="The full ID, not the session's name."
                        >
                          <Input
                            required
                            dir="ltr"
                            {...f('openwa_instance_id')}
                            value={pairing?.session_id || form.openwa_instance_id}
                          />
                        </Field>
                        <Field label="OpenWA API key">
                          <Input
                            type="password"
                            autoComplete="off"
                            {...f('openwa_api_key')}
                            disabled={Boolean(pairing)}
                          />
                        </Field>
                      </>
                    )}
                    {mode === 'manual' && (
                      <Field
                        label="Phone number (optional)"
                        hint="Only shown here, to tell phones apart."
                      >
                        <Input dir="ltr" {...f('phone_number')} />
                      </Field>
                    )}
                  </>
                )}
                {mode === 'automatic' && pairing?.phone_number && (
                  <p>Connected phone: +{pairing.phone_number}</p>
                )}
                {mode === 'manual' && (
                  <Button type="submit" variant="primary" size="lg" disabled={add.isPending}>
                    Add phone
                  </Button>
                )}
                {mode === 'automatic' && add.isPending && (
                  <p role="status">Saving the paired phone in Iris…</p>
                )}
                {mode === 'automatic' && add.isError && (
                  <div className="flex flex-col gap-2">
                    <p role="alert">
                      {add.error instanceof Error
                        ? add.error.message
                        : 'The phone could not be saved.'}
                    </p>
                    <Button type="button" onClick={() => add.mutate()} disabled={add.isPending}>
                      Retry saving phone
                    </Button>
                  </div>
                )}
              </form>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(savedPhone)}
        onOpenChange={(value) => {
          if (!value && !rename.isPending) setSavedPhone(null)
        }}
      >
        <DialogContent
          title="Phone connected"
          description="Already saved in Iris. You can optionally give it a friendly name."
        >
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (optionalName.trim()) rename.mutate()
              else setSavedPhone(null)
            }}
          >
            <Field
              label={
                defaultRole === 'parent' ? "Parent's name (optional)" : "Child's name (optional)"
              }
              hint={`Current name: ${savedPhone?.kid_name || ''}`}
            >
              <Input
                value={optionalName}
                onChange={(event) => setOptionalName(event.target.value)}
                disabled={rename.isPending}
              />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => setSavedPhone(null)} disabled={rename.isPending}>
                Done
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={rename.isPending || !optionalName.trim()}
              >
                Save name
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

type AlertChannel = 'openwa' | 'greenapi' | 'smtp' | 'telegram'

function ParentRecipients({ channel }: { channel?: string }) {
  const qc = useQueryClient()
  const accounts = useQuery({
    queryKey: ['users'],
    queryFn: () =>
      api<
        {
          id: number
          username: string
          role: string
          email: string | null
          email_verified: boolean
          whatsapp_number: string | null
        }[]
      >('/api/users'),
  })
  const registeredParents = Array.isArray(accounts.data)
    ? accounts.data.filter((user) => user.role !== 'watch' && (user.email || user.whatsapp_number))
    : []
  const { data } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
  const children = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const selectedChannel = channel ?? (data?.['alerts.channel'] as AlertChannel) ?? 'openwa'
  const contacts = (data?.['alerts.recipient_contacts'] ?? {}) as Record<
    string,
    { email?: string; telegram_chat_id?: string }
  >
  const [contactDrafts, setContactDrafts] = useState<
    Record<string, { email?: string; telegram_chat_id?: string }>
  >({})
  const contactSave = useMutation({
    mutationFn: (value: typeof contacts) =>
      api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ settings: { 'alerts.recipient_contacts': value } }),
      }),
    onSuccess: () => {
      setContactDrafts({})
      return qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: fail('Could not save parent destinations.'),
  })
  const assignments = (data?.['alerts.recipient_children'] ?? {}) as Record<string, number[]>
  const assign = useMutation({
    mutationFn: (next: Record<string, number[]>) =>
      api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ settings: { 'alerts.recipient_children': next } }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
    onError: fail('Could not save child assignments.'),
  })
  const canonical = (value: string) =>
    value.startsWith('email:')
      ? value.toLowerCase()
      : value.includes('@') && !value.endsWith('@c.us') && !value.endsWith('@g.us')
        ? 'email:' + value.toLowerCase()
        : value.includes('@')
          ? value
          : value.replace(/[^0-9]/g, '') + '@c.us'
  const [phone, setPhone] = useState('')
  const values =
    typeof data?.['alerts.recipient'] === 'string' ? (data['alerts.recipient'] as string) : ''
  const targets = values
    .split(/[,;\n]/)
    .map((value) => value.trim())
    .filter(Boolean)
  const change = useMutation({
    mutationFn: (recipient: string) =>
      api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          settings: {
            'alerts.recipient': recipient || null,
            'alerts.recipient_children': Object.fromEntries(
              Object.entries(assignments).filter(([parent]) =>
                recipient.split(/[,;\n]/).some((target) => canonical(target.trim()) === parent),
              ),
            ),
          },
        }),
      }),
    onSuccess: () => {
      setPhone('')
      toast.success('Parent recipients saved.')
      return qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: fail('Could not save parent recipients.'),
  })
  return (
    <section className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
      <h2 id="parent-alert-recipients" tabIndex={-1} className="scroll-mt-6 text-lg font-semibold">
        Parent alert recipients
      </h2>
      <p className="text-sm text-muted-foreground">
        Choose which children each parent receives alerts for. All children is the default.
        Selecting no children pauses alerts for that parent. Up to ten recipients.
      </p>
      <p className="text-sm text-muted-foreground">
        The channel selected in Alert delivery applies to every recipient.
        {selectedChannel === 'smtp' && ' Email alerts use the email saved in Users.'}
        {selectedChannel === 'telegram' &&
          ' Set the private or group Telegram chat ID for each recipient below.'}
      </p>
      <ul className="flex flex-col gap-2">
        {targets.map((target) => (
          <li
            key={target}
            className={`grid min-w-0 gap-3 rounded-md border p-3 lg:items-center ${selectedChannel === 'telegram' ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]' : 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]'}`}
          >
            <span dir="ltr" className="break-all">
              {/^\d+$/.test(target) ? `+${target}` : target}
            </span>
            <div className="flex flex-wrap gap-3 text-sm">
              <label>
                <input
                  type="checkbox"
                  checked={assignments[canonical(target)] === undefined}
                  disabled={assign.isPending}
                  onChange={(e) => {
                    const next = { ...assignments }
                    if (e.target.checked) delete next[canonical(target)]
                    else next[canonical(target)] = []
                    assign.mutate(next)
                  }}
                />{' '}
                All children (default)
              </label>
              {assignments[canonical(target)] !== undefined &&
                children.data
                  ?.filter((c) => c.role !== 'parent')
                  .map((c) => (
                    <label key={c.id}>
                      <input
                        type="checkbox"
                        disabled={assign.isPending}
                        checked={assignments[canonical(target)].includes(c.id)}
                        onChange={(e) => {
                          const current = assignments[canonical(target)]
                          assign.mutate({
                            ...assignments,
                            [canonical(target)]: e.target.checked
                              ? [...current, c.id]
                              : current.filter((id) => id !== c.id),
                          })
                        }}
                      />{' '}
                      {c.kid_name}
                    </label>
                  ))}
            </div>
            {selectedChannel === 'telegram' && (
              <div className="grid min-w-0 gap-2">
                <Input
                  aria-label={`Telegram chat ID for ${target}`}
                  placeholder="Individual or group Telegram chat ID"
                  value={
                    (contactDrafts[canonical(target)] ?? contacts[canonical(target)])
                      ?.telegram_chat_id ?? ''
                  }
                  onChange={(e) =>
                    setContactDrafts({
                      ...contactDrafts,
                      [canonical(target)]: {
                        ...(contactDrafts[canonical(target)] ?? contacts[canonical(target)]),
                        telegram_chat_id: e.target.value,
                      },
                    })
                  }
                />
                <Button
                  variant="outline"
                  disabled={!contactDrafts[canonical(target)] || contactSave.isPending}
                  onClick={() =>
                    contactSave.mutate({
                      ...contacts,
                      [canonical(target)]: contactDrafts[canonical(target)],
                    })
                  }
                >
                  Save Telegram destination
                </Button>
              </div>
            )}
            <Button
              variant="outline"
              onClick={() => change.mutate(targets.filter((value) => value !== target).join(', '))}
              aria-label={`Remove parent ${target}`}
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>
      {!targets.length && <p>No parent recipients yet.</p>}
      {registeredParents.length > 0 && (
        <Field
          label="Choose a parent"
          hint="Select their Iris account. Alert delivery selects the channel; WhatsApp alerts use their number saved in Users."
        >
          <Select
            aria-label="Choose a parent"
            value=""
            disabled={change.isPending}
            onChange={(event) => {
              if (event.target.value) change.mutate([...targets, event.target.value].join(', '))
            }}
          >
            <option value="">Choose a parent…</option>
            {registeredParents.map((user) => (
              <option
                key={user.id}
                value={user.email || user.whatsapp_number!}
                disabled={targets.some((target) =>
                  [user.email, user.whatsapp_number].some(
                    (contact) => contact && canonical(target) === canonical(contact),
                  ),
                )}
              >
                {user.username}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <form
        className="flex flex-col items-start gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          change.mutate([...targets, phone].join(', '))
        }}
      >
        <Field
          label="Parent number, email or WhatsApp group ID"
          className="w-full max-w-sm"
          hint="Select a parent by their email or phone number, or add a WhatsApp group ID ending in @g.us. Alert delivery determines the channel."
        >
          <Input
            aria-label="Parent phone number"
            type="text"
            inputMode="text"
            dir="ltr"

            title="Enter a parent email address, an international phone number, or a WhatsApp group ID."
            required
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="parent@example.com or +15550100101"
          />
        </Field>
        <Button type="submit" variant="primary" disabled={change.isPending}>
          Add parent
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">
        Number format is checked when saved. Ownership and WhatsApp registration are not verified.
      </p>
    </section>
  )
}

export function ParentConnections({
  showSender = true,
  channel,
}: {
  showSender?: boolean
  channel?: string
}) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
    refetchInterval: 10_000,
  })
  const { data: alertSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
  const senderId = Number(alertSettings?.['alerts.sender_instance_id'])
  const parents = data?.filter((phone) => phone.role === 'parent' || phone.id === senderId)
  if (!showSender) return <ParentRecipients channel={channel} />
  return (
    <div className="flex flex-col gap-4">
      <ParentRecipients channel={channel} />
      <h2 className="text-lg font-semibold">Alert sender connections</h2>
      <p className="text-sm text-muted-foreground">
        One connected WhatsApp number sends alerts to all parent recipients. Sender connections are
        not monitored.
      </p>
      <p className="text-sm text-muted-foreground">
        Two or more sender connections are optional. You can keep a primary, secondary and
        additional backup sender in case a number is blocked or disconnected. If the active sender
        becomes unavailable, manually select another connected sender below. Iris does not switch
        senders automatically.
      </p>
      <AddPhone defaultRole="parent" />
      {isLoading && <p>Loading sender connections…</p>}
      {isError && <Button onClick={() => void refetch()}>Retry loading sender connections</Button>}
      <ul className="flex flex-col gap-4">
        {parents?.map((phone) => (
          <PhoneCard key={phone.id} i={phone} senderConnection />
        ))}
      </ul>
      {parents?.length === 0 && <p>No alert sender connected yet.</p>}
    </div>
  )
}
