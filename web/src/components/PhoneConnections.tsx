import { t } from '../lib/i18n'
import { he } from '../lib/he'
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

export function PhoneCard({ i }: { i: Instance }) {
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
    onError: fail(he('Could not check this session.')),
  })
  const register = useMutation({
    mutationFn: () => api(`/api/instances/${i.id}/register-webhook`, { method: 'POST' }),
    onSuccess: () => {
      toast.success(he('Webhook registered in OpenWA for {name}.', { name: i.kid_name }))
      return refresh()
    },
    onError: fail(he('Could not register the webhook.')),
  })
  const rotate = useMutation({
    mutationFn: () => api(`/api/instances/${i.id}/rotate-token`, { method: 'POST' }),
    onSuccess: () => {
      toast.success(he('New webhook address created. Register it in OpenWA again.'))
      return refresh()
    },
    onError: fail(he('Could not rotate the token.')),
  })
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api(`/api/instances/${i.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
    onSuccess: (_d, enabled) => {
      toast.success(
        enabled
          ? he('Watching {name} again.', { name: i.kid_name })
          : he('Paused watching {name}.', { name: i.kid_name }),
      )
      return refresh()
    },
    onError: fail(he('Could not change this phone.')),
  })
  const changeRole = useMutation({
    mutationFn: (role: 'child' | 'parent') =>
      api(`/api/instances/${i.id}`, { method: 'PATCH', body: JSON.stringify({ role }) }),
    onSuccess: () => refresh(),
    onError: fail(he('Could not change the phone role.')),
  })
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
      await api(`/api/instances/${i.id}`, { method: 'DELETE' })
      setRemovalStage(4)
    },
    onSuccess: () => {
      toast.success(he('{name} removed.', { name: i.kid_name }))
      void qc.invalidateQueries({ queryKey: ['stats'] })
      return refresh()
    },
    onError: (error) =>
      setRemovalError(error instanceof Error ? error.message : he('Could not remove this phone.')),
  })
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(i.webhook_url)
      toast.success(he('Webhook address copied.'))
    } catch {
      toast.error(he('Could not copy. Select the address and copy it by hand.'))
    }
  }
  const parent = i.role === 'parent'
  return (
    <li className="flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-3">
        <KidAvatar name={i.kid_name} className="size-10 text-base" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-lg font-semibold">{i.kid_name}</span>
          <span className="truncate text-sm text-muted-foreground">
            {i.openwa_base_url}
            {t('instances.session', i.session_name || i.openwa_instance_id.slice(0, 8))}
          </span>
        </div>
        {!parent && (
          <label className="flex items-center gap-2 text-sm font-medium">
            {i.enabled ? he('Monitoring enabled') : he('Paused')}
            <Switch
              checked={i.enabled}
              onCheckedChange={(v) => toggle.mutate(v)}
              aria-label={he('Watch {name}', { name: i.kid_name })}
            />
          </label>
        )}
        {parent && <Badge tone="neutral">{he('Parent connection')}</Badge>}
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
            ? he('WhatsApp connected')
            : i.connection_status === 'qr_ready' || i.connection_status === 'action_required'
              ? he('WhatsApp needs re-pairing')
              : i.connection_status === 'disconnected'
                ? he('WhatsApp disconnected')
                : i.connection_status === 'initializing' || i.connection_status === 'authenticating'
                  ? he('WhatsApp connecting')
                  : i.connection_status === 'unreachable'
                    ? he('OpenWA unreachable')
                    : i.connection_status === 'missing'
                      ? he('OpenWA session missing')
                      : i.connection_status === 'failed'
                        ? he('WhatsApp connection failed')
                        : he('Connection not checked')}
        </Badge>
        {i.connection_checked_at && (
          <span className="text-xs text-muted-foreground">
            {he('Checked')}
            {relativeTime(i.connection_checked_at)}
          </span>
        )}
        <Button
          variant="outline"
          onClick={() => checkSession.mutate()}
          disabled={checkSession.isPending}
        >
          {checkSession.isPending ? he('Checking…') : he('Check connection')}
        </Button>
      </div>
      {i.enabled &&
        i.connection_status &&
        !['ready', 'unknown', 'initializing', 'authenticating'].includes(i.connection_status) && (
          <p role="alert" className="text-sm text-danger">
            {he(
              'Monitoring is enabled, but this phone is not connected. New messages cannot be checked until WhatsApp reconnects.',
            )}
          </p>
        )}
      <RepairPhone phone={i} open={repairOpen} onOpenChange={setRepairOpen} />
      <Field label={he('Role for {name}', { name: i.kid_name })}>
        <Select
          value={i.role || 'child'}
          onChange={(event) => changeRole.mutate(event.target.value as 'child' | 'parent')}
        >
          <option value="child">{he('Child — monitored when watching is enabled')}</option>
          <option value="parent">{he('Parent — alert delivery only')}</option>
        </Select>
      </Field>
      {!parent && (
        <>
          <p className="text-sm">
            {i.last_webhook_at ? (
              <>
                {he('Last message received')}
                <strong>{relativeTime(i.last_webhook_at)}</strong>.
              </>
            ) : (
              <Badge tone="warning">{he('Nothing received yet')}</Badge>
            )}
            {!i.last_webhook_at && (
              <span className="ms-2 text-muted-foreground">
                {he('Register the webhook below, then send a test message.')}
              </span>
            )}
          </p>
          <div className="flex flex-col gap-1.5">
            <span aria-hidden className="text-sm font-medium">
              {he('Webhook address')}
            </span>
            <div className="flex items-stretch gap-2">
              <Input
                readOnly
                dir="ltr"
                aria-label={he('Webhook address')}
                value={i.webhook_url}
                onFocus={(e) => e.currentTarget.select()}
                className="min-w-0 flex-1 font-mono text-xs"
              />
              <Button
                variant="outline"
                size="icon"
                aria-label={he('Copy webhook address')}
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
              <Link2 />
              {he('Register in OpenWA')}
            </Button>
            <ConfirmDialog
              trigger={
                <Button variant="outline">
                  <RefreshCw />
                  {he('New webhook address')}
                </Button>
              }
              title={he('Create a new webhook address?')}
              description={he(
                "The current address stops working immediately. You must register the new one in OpenWA before {name}'s messages are checked again.",
                { name: i.kid_name },
              )}
              confirmLabel={he('Create new address')}
              tone="primary"
              onConfirm={() => rotate.mutate()}
            />
          </div>
        </>
      )}
      {parent && (
        <p className="text-sm">
          {he(
            "Used for alert delivery. This phone's messages are not monitored. Choose the alert sender in",
          )}
          <Link to="/settings">{he('Settings')}</Link>.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <ConfirmDialog
          trigger={
            <Button variant="danger-outline" className="ms-auto">
              <Trash2 />
              {he('Remove')}
            </Button>
          }
          title={he('Remove {name}?', { name: i.kid_name })}
          description={
            parent
              ? he(
                  'This parent connection is removed. Select another sender in Settings if it is used for alert delivery.',
                )
              : he(
                  'Iris stops watching this phone. Messages already saved stay until the retention window removes them.',
                )
          }
          confirmLabel={he('Remove phone')}
          onConfirm={() => remove.mutateAsync(deleteOpenWA)}
          pending={remove.isPending}
          keepOpen
          onOpenChange={(open) => {
            if (open) {
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
              {he('Also delete the OpenWA session')}
              <span className="mt-1 block text-muted-foreground">
                {he(
                  'Unlinks WhatsApp and deletes its saved session. Leave unchecked to remove only from Iris.',
                )}
              </span>
            </span>
          </label>
          {removalStage > 0 && (
            <div className="flex flex-col gap-2" aria-live="polite">
              <progress
                aria-label={he('Phone removal progress')}
                className="h-3 w-full"
                max={deleteOpenWA ? 3 : 1}
                value={deleteOpenWA ? Math.min(removalStage - 1, 3) : removalStage === 4 ? 1 : 0}
              />
              <p role="status">
                {removalStage === 4
                  ? he('Phone removed.')
                  : deleteOpenWA
                    ? [
                        '',
                        he('Deactivating WhatsApp…'),
                        he('Deleting the OpenWA session…'),
                        he('Removing the Iris entry…'),
                      ][removalStage]
                    : he('Removing the Iris entry…')}
              </p>
              {deleteOpenWA && (
                <ol className="text-sm text-muted-foreground">
                  <li>
                    {removalStage > 1 ? '✓ ' : ''}
                    {he('Deactivate WhatsApp')}
                  </li>
                  <li>
                    {removalStage > 2 ? '✓ ' : ''}
                    {he('Delete OpenWA session')}
                  </li>
                  <li>
                    {removalStage > 3 ? '✓ ' : ''}
                    {he('Remove Iris entry')}
                  </li>
                </ol>
              )}
            </div>
          )}
          {removalError && (
            <p role="alert" className="text-sm text-danger">
              {removalError}
              {he('You can retry removal.')}
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
            : he('{name} added. Register the webhook to start watching.', { name: form.kid_name }),
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
    onError: fail(he('Could not add the phone. Check the OpenWA address and try again.')),
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
    onError: fail(he('Could not save the name. The phone is already connected.')),
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
            <Plus />
            {he('Add a phone')}
          </Button>
        </DialogTrigger>
        <DialogContent
          title={he('Add a phone')}
          description={
            defaultRole === 'child'
              ? he('Add a child phone to monitor its messages.')
              : he(
                  'Add a WhatsApp sender connection for parent alerts. Sender messages are not monitored.',
                )
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
              <TabsTrigger value="manual">{he('Manual')}</TabsTrigger>
              {pairingConfig?.configured && (
                <TabsTrigger value="automatic">{he('Automatic')}</TabsTrigger>
              )}
            </TabsList>
            <TabsContent value={mode}>
              <form onSubmit={submit} className="flex flex-col gap-4">
                {open && mode === 'automatic' && (
                  <PhonePairing name="" onChange={setPairing} savedToken={savedPairing} />
                )}
                {mode === 'manual' && (
                  <>
                    <Field
                      label={form.role === 'parent' ? he("Parent's name") : he("Child's name")}
                    >
                      <Input required={mode === 'manual'} {...f('kid_name')} />
                    </Field>
                    {mode === 'manual' && (
                      <>
                        <Field label={he('OpenWA address')}>
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
                          label={he('OpenWA session ID')}
                          hint={he("The full ID, not the session's name.")}
                        >
                          <Input
                            required
                            dir="ltr"
                            {...f('openwa_instance_id')}
                            value={pairing?.session_id || form.openwa_instance_id}
                          />
                        </Field>
                        <Field label={he('OpenWA API key')}>
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
                        label={he('Phone number (optional)')}
                        hint={he('Only shown here, to tell phones apart.')}
                      >
                        <Input dir="ltr" {...f('phone_number')} />
                      </Field>
                    )}
                  </>
                )}
                {mode === 'automatic' && pairing?.phone_number && (
                  <p>
                    {he('Connected phone: +')}
                    {pairing.phone_number}
                  </p>
                )}
                {mode === 'manual' && (
                  <Button type="submit" variant="primary" size="lg" disabled={add.isPending}>
                    {he('Add phone')}
                  </Button>
                )}
                {mode === 'automatic' && add.isPending && (
                  <p role="status">{he('Saving the paired phone in Iris…')}</p>
                )}
                {mode === 'automatic' && add.isError && (
                  <div className="flex flex-col gap-2">
                    <p role="alert">
                      {add.error instanceof Error
                        ? add.error.message
                        : he('The phone could not be saved.')}
                    </p>
                    <Button type="button" onClick={() => add.mutate()} disabled={add.isPending}>
                      {he('Retry saving phone')}
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
          title={he('Phone connected')}
          description={he('Already saved in Iris. You can optionally give it a friendly name.')}
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
                defaultRole === 'parent'
                  ? he("Parent's name (optional)")
                  : he("Child's name (optional)")
              }
              hint={he('Current name: {name}', { name: savedPhone?.kid_name || '' })}
            >
              <Input
                value={optionalName}
                onChange={(event) => setOptionalName(event.target.value)}
                disabled={rename.isPending}
              />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => setSavedPhone(null)} disabled={rename.isPending}>
                {he('Done')}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={rename.isPending || !optionalName.trim()}
              >
                {he('Save name')}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

function ParentRecipients() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
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
        body: JSON.stringify({ settings: { 'alerts.recipient': recipient || null } }),
      }),
    onSuccess: () => {
      setPhone('')
      toast.success(he('Parent recipients saved.'))
      return qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: fail(he('Could not save parent recipients.')),
  })
  return (
    <section className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
      <h2 className="text-lg font-semibold">{he('Parent alert recipients')}</h2>
      <p className="text-sm text-muted-foreground">
        {he(
          'These numbers receive alerts. They do not need their own OpenWA session. Up to ten recipients.',
        )}
      </p>
      <ul className="flex flex-col gap-2">
        {targets.map((target) => (
          <li key={target} className="flex items-center justify-between gap-3">
            <span dir="ltr">{/^\d+$/.test(target) ? `+${target}` : target}</span>
            <Button
              variant="outline"
              onClick={() => change.mutate(targets.filter((value) => value !== target).join(', '))}
              aria-label={he('Remove parent {name}', { name: target })}
            >
              {he('Remove')}
            </Button>
          </li>
        ))}
      </ul>
      {!targets.length && <p>{he('No parent recipients yet.')}</p>}
      <form
        className="flex flex-col items-start gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          change.mutate([...targets, phone].join(', '))
        }}
      >
        <Field
          label={he('Parent phone number')}
          className="w-full max-w-sm"
          hint={he(
            'Include the country code and omit the local leading zero. The + prefix is optional.',
          )}
        >
          <Input
            aria-label={he('Parent phone number')}
            type="tel"
            inputMode="tel"
            dir="ltr"
            pattern="\+?[1-9](?:[0-9]|\s|\(|\)|-){5,24}"
            title={he(
              'Enter an international phone number with its country code, for example +15550100101.',
            )}
            required
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="+15550100101"
          />
        </Field>
        <Button type="submit" variant="primary" disabled={change.isPending}>
          {he('Add parent')}
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">
        {he(
          'Number format is checked when saved. Ownership and WhatsApp registration are not verified.',
        )}
      </p>
    </section>
  )
}

export function ParentConnections() {
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
  return (
    <div className="flex flex-col gap-4">
      <ParentRecipients />
      <h2 className="text-lg font-semibold">{he('Alert sender connections')}</h2>
      <p className="text-sm text-muted-foreground">
        {he(
          'One connected WhatsApp number sends alerts to all parent recipients. Sender connections are not monitored.',
        )}
      </p>
      <p className="text-sm text-muted-foreground">
        {he(
          'Two or more sender connections are optional. You can keep a primary, secondary and additional backup sender in case a number is blocked or disconnected. If the active sender becomes unavailable, manually select another connected sender below. Iris does not switch senders automatically.',
        )}
      </p>
      <AddPhone defaultRole="parent" />
      {isLoading && <p>{he('Loading sender connections…')}</p>}
      {isError && (
        <Button onClick={() => void refetch()}>{he('Retry loading sender connections')}</Button>
      )}
      <ul className="flex flex-col gap-4">
        {parents?.map((phone) => (
          <PhoneCard key={phone.id} i={phone} />
        ))}
      </ul>
      {parents?.length === 0 && <p>{he('No alert sender connected yet.')}</p>}
    </div>
  )
}
