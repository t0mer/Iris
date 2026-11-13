import { t } from '../lib/i18n'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '../lib/notify'
import { api } from '../lib/api'
import type { AlertReadiness } from '../lib/types'
import { ConfirmDialog } from '../components/ui/dialog'
import { Button } from '../components/ui/button'
import { Field, Input, Select } from '../components/ui/field'

type User = {
  id: number
  username: string
  role: 'admin' | 'parent' | 'watch'
  email: string | null
  whatsapp_number: string | null
  email_verified?: boolean
  whatsapp_verified?: boolean
}
type SMTP = {
  host: string
  port: number
  tls: string
  username: string
  sender: string
  verified?: boolean
}
const emptyUser = {
  username: '',
  role: 'watch' as const,
  email: '',
  whatsapp_number: '',
  password: '',
}

export function UserSettings() {
  const qc = useQueryClient()
  const readiness = useQuery({
    queryKey: ['alert-readiness'],
    queryFn: () => api<AlertReadiness>('/api/settings/alert-readiness'),
    refetchInterval: 30_000,
  })
  const users = useQuery({
    // Refresh after the recipient confirms a link in another browser.
    queryKey: ['users'],
    queryFn: () => api<User[]>('/api/users'),
    refetchInterval: 10_000,
  })
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
  const security = useQuery({
    queryKey: ['security'],
    queryFn: () =>
      api<{
        smtp: Partial<SMTP>
        green_api?: { verified?: boolean }
        enabled: boolean
        password_set: boolean
      }>('/api/users/security/config'),
  })
  const [form, setForm] = useState<Omit<User, 'id'> & { password: string }>(emptyUser)
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [saveError, setSaveError] = useState('')
  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setSaveError('')
    try {
      await action()
      await qc.invalidateQueries({ queryKey: ['security'] })
      await qc.invalidateQueries({ queryKey: ['users'] })
      await qc.invalidateQueries({ queryKey: ['me'] })
      await qc.invalidateQueries({ queryKey: ['settings'] })
      await qc.invalidateQueries({ queryKey: ['alert-readiness'] })
      await qc.invalidateQueries({ queryKey: ['stats'] })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not save'
      setSaveError(message)
      toast.error(message)
    } finally {
      setBusy(false)
    }
  }
  const canEnable =
    users.data?.length &&
    users.data.every(
      (u) =>
        (u.email && u.email_verified && security.data?.smtp.verified) ||
        (u.whatsapp_number && u.whatsapp_verified && security.data?.green_api?.verified),
    )
  const emailReady =
    security.data?.smtp.verified && users.data?.some((u) => u.email && u.email_verified)
  const whatsappReady =
    security.data?.green_api?.verified &&
    users.data?.some((u) => u.whatsapp_number && u.whatsapp_verified)
  const availableChannels = [emailReady && 'email', whatsappReady && 'whatsapp'].filter(
    Boolean,
  ) as string[]
  const preferredChannel = String(settings.data?.['auth.default_channel'] || 'email')
  const defaultChannel = availableChannels.includes(preferredChannel)
    ? preferredChannel
    : availableChannels[0]
  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="text-lg font-semibold">{t('Users and roles')}</h2>
        <p className="text-sm text-muted-foreground">
          {t(
            'Watch users have read-only access to Home, Alerts, Review, Messages and Chats. Parents can resolve reviews, resend alerts, reprocess messages and delete saved media evidence. Admins also manage settings, users and phones. For 2FA, each user needs an approved email or personal WhatsApp number.',
          )}
        </p>
        {users.isError && <p role="alert">{t('Could not load users.')}</p>}
        <ul className="my-4 flex flex-col gap-2">
          {users.data?.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-3 rounded-md border p-3">
              <span>
                {u.username} · {u.role} · {u.email || 'No email'} ·{' '}
                {u.whatsapp_number || 'No WhatsApp number'}
              </span>
              {readiness.data?.users?.find((status) => status.id === u.id) &&
                (() => {
                  const status = readiness.data.users.find((status) => status.id === u.id)!
                  return (
                    <Link
                      to="/settings?tab=Notifications#parent-alert-recipients"
                      className={`text-sm underline underline-offset-2 ${status.eligible ? 'text-success' : 'text-warning'}`}
                    >
                      {t('Alerts:')} {status.eligible ? t('Eligible') : t(status.reason ?? '')}
                    </Link>
                  )
                })()}
              {u.email &&
                (u.email_verified ? (
                  <span className="text-sm text-success">{t('Email approved')}</span>
                ) : (
                  <Button
                    disabled={busy || !security.data?.smtp.verified}
                    aria-label={t('Send email approval for {value0}', { value0: u.username })}
                    onClick={() =>
                      void run(async () => {
                        await api(`/api/users/${u.id}/approve-contact`, {
                          method: 'POST',
                          body: JSON.stringify({ channel: 'email' }),
                        })
                        toast.success('Email approval link sent.')
                      })
                    }
                  >
                    {t('Send email approval')}
                  </Button>
                ))}
              {u.whatsapp_number &&
                (u.whatsapp_verified ? (
                  <span className="text-sm text-success">{t('WhatsApp approved')}</span>
                ) : (
                  <Button
                    disabled={
                      busy ||
                      (!security.data?.green_api?.verified &&
                        !settings.data?.['alerts.sender_instance_id'])
                    }
                    aria-label={t('Send WhatsApp approval for {value0}', { value0: u.username })}
                    onClick={() =>
                      void run(async () => {
                        await api(`/api/users/${u.id}/approve-contact`, {
                          method: 'POST',
                          body: JSON.stringify({ channel: 'whatsapp' }),
                        })
                        toast.success(
                          'Approval link sent. Open it on the recipient’s WhatsApp and confirm ownership; sending alone does not approve the number.',
                        )
                      })
                    }
                  >
                    {t('Send WhatsApp approval')}
                  </Button>
                ))}

              <Button
                onClick={() => {
                  setSaveError('')
                  setEditing(u.id)
                  setForm({ ...u, password: '' })
                }}
              >
                {t('Edit')}
              </Button>
              {u.role !== 'admin' && (
                <ConfirmDialog
                  title={t('Delete {value0}?', { value0: u.username })}
                  description={t(
                    'This removes the user account and its login access. Monitored phones and messages are retained.',
                  )}
                  confirmLabel={t('Delete user')}
                  pending={busy}
                  trigger={
                    <Button
                      variant="danger"
                      disabled={busy}
                      aria-label={t('Delete user {value0}', { value0: u.username })}
                    >
                      {t('Delete user')}
                    </Button>
                  }
                  onConfirm={() =>
                    run(async () => {
                      await api(`/api/users/${u.id}`, { method: 'DELETE' })
                      if (editing === u.id) {
                        setEditing(null)
                        setForm(emptyUser)
                      }
                      toast.success('User deleted.')
                    })
                  }
                />
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="mb-4 text-lg font-semibold">{editing ? t('Edit user') : t('Add user')}</h2>
        {saveError && (
          <p role="alert" className="mb-3 text-sm text-danger">
            {t(saveError)}
          </p>
        )}
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (form.email && !/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(form.email.trim())) {
              setSaveError('Enter a valid email address, for example name@example.com.')
              return
            }
            void run(async () => {
              await api(editing ? `/api/users/${editing}` : '/api/users', {
                method: editing ? 'PUT' : 'POST',
                body: JSON.stringify({
                  username: form.username,
                  role: form.role,
                  email: form.email?.trim() || null,
                  whatsapp_number: form.whatsapp_number?.trim() || null,
                  password: form.password || undefined,
                }),
              })
              setEditing(null)
              setForm(emptyUser)
              toast.success('User saved.')
            })
          }}
        >
          <Field label={t('Username')}>
            <Input
              required
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
          </Field>
          <Field label={editing ? t('Reset this user’s password (optional)') : t('Password')}>
            <Input
              type="password"
              minLength={8}
              required={!editing}
              value={form.password}
              autoComplete="new-password"
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </Field>
          <Field label={t('Role')}>
            <Select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value as User['role'] })}
            >
              <option value="parent">{t('Parent')}</option>
              <option value="watch">{t('Watch only')}</option>
              <option value="admin">{t('Admin')}</option>
            </Select>
          </Field>
          <Field label={t('Email')}>
            <Input
              type="email"
              value={form.email || ''}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </Field>
          <Field label={t('Personal WhatsApp number')}>
            <Input
              type="tel"
              aria-label={t('Personal WhatsApp number')}
              autoComplete="tel"
              placeholder="+972501234567"
              value={form.whatsapp_number || ''}
              onChange={(e) => setForm({ ...form, whatsapp_number: e.target.value })}
            />
            <p className="text-sm text-muted-foreground">
              {t(
                'Optional. Leave empty to remove the number. Your personal number for receiving alerts and 2FA codes. It must differ from the GreenAPI sender number. Include + and country code. Codes are sent through GreenAPI configured in Settings → Notifications. Ownership approval can also use a connected OpenWA sender. Sending an approval request does not approve the number; the recipient must open the link and confirm it.',
              )}
            </p>
          </Field>
          <div className="flex items-end gap-2">
            <Button type="submit" disabled={busy}>
              {t('Save user')}
            </Button>
            {editing && (
              <Button
                type="button"
                onClick={() => {
                  setEditing(null)
                  setForm(emptyUser)
                }}
              >
                {t('Cancel')}
              </Button>
            )}
          </div>
        </form>
      </section>
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="text-lg font-semibold">{t('Two-factor authentication')}</h2>
        <p className="mb-3 text-sm">
          {security.data?.enabled
            ? t(
                '2FA is required at login. New users need a contact with a tested provider and must approve it before login. Disable 2FA before changing delivery providers.',
              )
            : t(
                'Test SMTP or GreenAPI in Settings → Notifications, then approve at least one contact per user to enable 2FA.',
              )}
        </p>
        <p className="mb-3 text-sm text-muted-foreground">
          {t(
            'Email codes use SMTP. WhatsApp 2FA uses GreenAPI only and includes a Copy code button. An approved email with tested SMTP or an approved WhatsApp number with tested GreenAPI is enough; both are optional alternatives. Approval links use Iris base URL in Settings → Notifications.',
          )}
        </p>
        <p className="mb-3 text-sm text-muted-foreground">
          {t(
            'If code delivery fails, emergency recovery requires access to the Iris Docker container and its predefined recovery key. No recovery-key bypass is available on this login page.',
          )}
        </p>
        {!!canEnable &&
          availableChannels.length > 0 &&
          !users.isError &&
          !security.isError &&
          !settings.isError &&
          settings.data && (
            <div className="mb-4 flex flex-col gap-3">
              <h3 className="font-semibold">{t('Sign-in verification')}</h3>
              <p className="text-sm text-muted-foreground">
                {t(
                  'Choose the preferred code channel from tested providers with approved user contacts. Each user can use a channel available to their account when signing in.',
                )}
              </p>
              <Field label={t('Default sign-in code channel')}>
                <Select
                  aria-label={t('Default sign-in code channel')}
                  value={defaultChannel}
                  disabled={busy}
                  onChange={(event) => {
                    const channel = event.target.value
                    void run(async () => {
                      await api('/api/settings', {
                        method: 'PUT',
                        body: JSON.stringify({ settings: { 'auth.default_channel': channel } }),
                      })
                      toast.success('Sign-in channel saved.')
                    })
                  }}
                >
                  {emailReady && <option value="email">{t('Email (default)')}</option>}
                  {whatsappReady && <option value="whatsapp">{t('WhatsApp via GreenAPI')}</option>}
                </Select>
              </Field>
            </div>
          )}
        <Button
          disabled={
            busy ||
            security.isLoading ||
            users.isError ||
            security.isError ||
            (!security.data?.enabled && !canEnable)
          }
          onClick={() =>
            void run(async () => {
              await api('/api/users/security/two-factor', {
                method: 'PUT',
                body: JSON.stringify({ enabled: !security.data?.enabled }),
              })
              toast.success('2FA settings saved.')
            })
          }
        >
          {security.data?.enabled ? t('Disable 2FA') : t('Enable 2FA')}
        </Button>
      </section>
    </div>
  )
}
