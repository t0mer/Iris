import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Link2, Plus, RefreshCw, Smartphone, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { EmptyState } from '../components/EmptyState'
import { KidAvatar } from '../components/KidAvatar'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { ConfirmDialog, Dialog, DialogContent, DialogTrigger } from '../components/ui/dialog'
import { Field, Input } from '../components/ui/field'
import { Skeleton } from '../components/ui/skeleton'
import { Switch } from '../components/ui/switch'
import { api, ApiError } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { Instance } from '../lib/types'

const fail = (fallback: string) => (e: unknown) =>
  toast.error(e instanceof ApiError ? e.message : fallback)

function PhoneCard({ i }: { i: Instance }) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['instances'] })
  const register = useMutation({
    mutationFn: () => api(`/api/instances/${i.id}/register-webhook`, { method: 'POST' }),
    onSuccess: () => {
      toast.success(`Webhook registered in OpenWA for ${i.kid_name}.`)
      return refresh()
    },
    onError: fail('Could not register the webhook.'),
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
  const remove = useMutation({
    mutationFn: () => api(`/api/instances/${i.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast.success(`${i.kid_name} removed.`)
      return refresh()
    },
    onError: fail('Could not remove this phone.'),
  })
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(i.webhook_url)
      toast.success('Webhook address copied.')
    } catch {
      toast.error('Could not copy. Select the address and copy it by hand.')
    }
  }
  return (
    <li className="flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-3">
        <KidAvatar name={i.kid_name} className="size-10 text-base" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-lg font-semibold">{i.kid_name}</span>
          <span className="truncate text-sm text-muted-foreground">
            {i.openwa_base_url}, session {i.openwa_instance_id.slice(0, 8)}
          </span>
        </div>
        <label className="flex items-center gap-2 text-sm font-medium">
          {i.enabled ? 'Watching' : 'Paused'}
          <Switch
            checked={i.enabled}
            onCheckedChange={(v) => toggle.mutate(v)}
            aria-label={`Watch ${i.kid_name}`}
          />
        </label>
      </div>
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
        <Button variant="primary" onClick={() => register.mutate()} disabled={register.isPending}>
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
        <ConfirmDialog
          trigger={
            <Button variant="danger-outline" className="ms-auto">
              <Trash2 /> Remove
            </Button>
          }
          title={`Remove ${i.kid_name}?`}
          description="Iris stops watching this phone. Messages already saved stay until the retention window removes them."
          confirmLabel="Remove phone"
          onConfirm={() => remove.mutate()}
        />
      </div>
    </li>
  )
}

function AddPhone() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    kid_name: '',
    phone_number: '',
    openwa_base_url: '',
    openwa_instance_id: '',
    openwa_api_key: '',
  })
  const add = useMutation({
    mutationFn: () =>
      api('/api/instances', {
        method: 'POST',
        body: JSON.stringify({ ...form, phone_number: form.phone_number || null }),
      }),
    onSuccess: () => {
      toast.success(`${form.kid_name} added. Register the webhook to start watching.`)
      setForm({
        kid_name: '',
        phone_number: '',
        openwa_base_url: '',
        openwa_instance_id: '',
        openwa_api_key: '',
      })
      setOpen(false)
      return qc.invalidateQueries({ queryKey: ['instances'] })
    },
    onError: fail('Could not add the phone. Check the OpenWA address and try again.'),
  })
  const f = (k: keyof typeof form) => ({
    value: form[k],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value }),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary">
          <Plus /> Add a phone
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Add a phone"
        description="One phone is one child's WhatsApp number, connected through an OpenWA session."
      >
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Child's name">
            <Input required {...f('kid_name')} />
          </Field>
          <Field label="OpenWA address">
            <Input
              required
              type="url"
              dir="ltr"
              placeholder="https://openwa.example.com"
              {...f('openwa_base_url')}
            />
          </Field>
          <Field label="OpenWA session ID" hint="The full ID, not the session's name.">
            <Input required dir="ltr" {...f('openwa_instance_id')} />
          </Field>
          <Field label="OpenWA API key">
            <Input type="password" autoComplete="off" {...f('openwa_api_key')} />
          </Field>
          <Field label="Phone number (optional)" hint="Only shown here, to tell phones apart.">
            <Input dir="ltr" {...f('phone_number')} />
          </Field>
          <Button type="submit" variant="primary" size="lg" disabled={add.isPending}>
            Add phone
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function Instances() {
  const { data, isLoading } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
    refetchInterval: 60_000,
  })
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="Phones"
        description="The children's numbers Iris watches. Each one connects through its own OpenWA session."
        actions={<AddPhone />}
      />
      {isLoading && <Skeleton className="h-48" />}
      <ul className="flex flex-col gap-4">
        {data?.map((i) => (
          <PhoneCard key={i.id} i={i} />
        ))}
      </ul>
      {data?.length === 0 && (
        <div className="rounded-lg border bg-surface">
          <EmptyState icon={Smartphone} title="No phones yet">
            Add the first child's number to start watching. You will need an OpenWA session for it.
          </EmptyState>
        </div>
      )}
    </div>
  )
}
