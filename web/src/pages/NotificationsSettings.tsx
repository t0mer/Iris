import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Button } from '../components/ui/button'
import { Field, Input, Select } from '../components/ui/field'
import { PageLoading } from '../components/PageLoading'
import { QueryError } from '../components/QueryError'

type SMTP = {
  host: string
  port: number
  tls: string
  username: string
  sender: string
  verified?: boolean
}
type GreenAPI = {
  media_url?: string
  api_url: string
  instance_id: string
  verified?: boolean
  sender_number?: string
}
const emptyGreen = { api_url: 'https://api.green-api.com', instance_id: '', token: '' }
const emptySMTP = {
  host: '',
  port: 587,
  tls: 'starttls',
  username: '',
  sender: '',
  password: '',
}

type SecurityConfig = {
  smtp: Partial<SMTP>
  green_api?: Partial<GreenAPI>
  green_api_token_set?: boolean
  enabled: boolean
  password_set: boolean
}
const loadSecurity = () => api<SecurityConfig>('/api/users/security/config')

export function NotificationsSettings() {
  const security = useQuery({ queryKey: ['security'], queryFn: loadSecurity })
  if (!security.data && security.isError)
    return <QueryError what="notification settings" onRetry={() => void security.refetch()} />
  if (!security.data) return <PageLoading />
  return <NotificationForm initial={security.data} />
}

function NotificationForm({ initial }: { initial: SecurityConfig }) {
  const qc = useQueryClient()
  const security = useQuery({
    queryKey: ['security'],
    queryFn: loadSecurity,
  })
  const [green, setGreen] = useState(() => ({ ...emptyGreen, ...initial.green_api, token: '' }))
  const [greenResult, setGreenResult] = useState('')
  const [greenFailed, setGreenFailed] = useState(false)
  const [smtp, setSMTP] = useState(() => ({ ...emptySMTP, ...initial.smtp, password: '' }))
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  const [smtpFailed, setSMTPFailed] = useState(false)
  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    try {
      await action()
      await qc.invalidateQueries({ queryKey: ['security'] })
      await qc.invalidateQueries({ queryKey: ['stats'] })
      await qc.invalidateQueries({ queryKey: ['users'] })
      await qc.invalidateQueries({ queryKey: ['me'] })
      await qc.invalidateQueries({ queryKey: ['alert-readiness'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="text-lg font-medium">SMTP server</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          This SMTP server delivers email alerts and sign-in codes. Enter its host, port, TLS mode
          and credentials. Configure your admin email in Settings → Users, then save and send a
          test. Open its approval link to approve the email for 2FA. Approval links use Iris base
          URL in Settings → Alerts.
        </p>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              await api('/api/users/security/smtp', { method: 'PUT', body: JSON.stringify(smtp) })
              setResult('SMTP saved. Run the test before enabling 2FA.')
              setSMTPFailed(false)
            })
          }}
        >
          <Field label="SMTP provider">
            <Select
              value={smtp.host === 'smtp.gmail.com' ? 'gmail' : 'custom'}
              onChange={(e) =>
                setSMTP({
                  ...smtp,
                  host: e.target.value === 'gmail' ? 'smtp.gmail.com' : '',
                  port: 587,
                  tls: 'starttls',
                  password: '',
                })
              }
            >
              <option value="custom">Custom SMTP / other provider</option>
              <option value="gmail">Gmail</option>
            </Select>
          </Field>
          <Field label="SMTP host">
            <Input
              required
              value={smtp.host}
              onChange={(e) => setSMTP({ ...smtp, host: e.target.value })}
            />
          </Field>
          <Field label="Port">
            <Input
              type="number"
              required
              min={1}
              max={65535}
              value={smtp.port}
              onChange={(e) => setSMTP({ ...smtp, port: Number(e.target.value) })}
            />
          </Field>
          <Field label="Security">
            <Select value={smtp.tls} onChange={(e) => setSMTP({ ...smtp, tls: e.target.value })}>
              <option value="starttls">STARTTLS</option>
              <option value="ssl">SSL / TLS</option>
            </Select>
          </Field>
          <Field label="SMTP username">
            <Input
              required
              value={smtp.username}
              onChange={(e) => setSMTP({ ...smtp, username: e.target.value })}
            />
          </Field>
          <Field label="SMTP password">
            <Input
              type="password"
              value={smtp.password}
              autoComplete="new-password"
              placeholder={security.data?.password_set ? 'Saved (leave blank to keep)' : ''}
              onChange={(e) => setSMTP({ ...smtp, password: e.target.value })}
            />
          </Field>
          <Field label="Sender email">
            <Input
              type="email"
              required
              value={smtp.sender}
              onChange={(e) => setSMTP({ ...smtp, sender: e.target.value })}
            />
          </Field>
          <Button type="submit" disabled={busy || security.data?.enabled}>
            Save SMTP
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const r = await api<{ ok: boolean; detail: string }>(
                  '/api/users/security/smtp/test',
                  { method: 'POST' },
                )
                setResult(r.detail)
                setSMTPFailed(!r.ok)
              })
            }
          >
            Test saved SMTP
          </Button>
        </form>
        {smtp.host === 'smtp.gmail.com' && (
          <p className="mt-3 text-sm text-muted-foreground">
            Gmail uses your full email username and a Google app password. Choose STARTTLS port 587
            or SSL / TLS port 465.
          </p>
        )}
        <p
          role={smtpFailed ? 'alert' : 'status'}
          className={`mt-3 text-sm ${smtpFailed ? 'text-danger' : ''}`}
        >
          {result ||
            (security.data?.smtp.verified ? 'SMTP test passed.' : 'SMTP has not passed its test.')}
        </p>
      </section>
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="text-lg font-medium">GreenAPI — WhatsApp 2FA</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          GreenAPI sends WhatsApp alerts to individual numbers or group IDs. Sign-in codes use
          personal numbers with a Copy code button. Save your GreenAPI credentials, then send a test
          to your personal WhatsApp number configured in Settings → Users. Open the approval link in
          the test message. An approved email with tested SMTP or an approved WhatsApp number with
          tested GreenAPI is enough to enable 2FA.
        </p>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              await api('/api/users/security/whatsapp', {
                method: 'PUT',
                body: JSON.stringify({
                  ...green,
                  token: green.token || undefined,
                }),
              })
              setGreen((g) => ({ ...g, token: '' }))
              setGreenResult(
                'GreenAPI saved. Check the sender account, then test delivery. Personal recipient numbers must be different from this sender.',
              )
              setGreenFailed(false)
            })
          }}
        >
          <Field label="GreenAPI API URL">
            <Input
              required
              type="url"
              value={green.api_url}
              onChange={(e) => setGreen({ ...green, api_url: e.target.value })}
            />
          </Field>
          <Field
            label="GreenAPI media URL"
            hint="Optional media endpoint from your GreenAPI account. Text alerts use the API URL."
          >
            <Input
              type="url"
              value={green.media_url ?? ''}
              onChange={(e) => setGreen({ ...green, media_url: e.target.value })}
            />
          </Field>
          <Field label="GreenAPI instance ID">
            <Input
              required
              inputMode="numeric"
              value={green.instance_id}
              onChange={(e) => setGreen({ ...green, instance_id: e.target.value })}
            />
          </Field>
          <Field label="GreenAPI API token">
            <Input
              type="password"
              autoComplete="new-password"
              required={!security.data?.green_api_token_set}
              placeholder={security.data?.green_api_token_set ? 'Saved — leave blank to keep' : ''}
              value={green.token}
              onChange={(e) => setGreen({ ...green, token: e.target.value })}
            />
          </Field>
          <div className="flex flex-wrap items-end gap-2">
            <Button type="submit" disabled={busy || security.data?.enabled}>
              Save GreenAPI
            </Button>
            <Button
              type="button"
              disabled={busy || !security.data?.green_api_token_set}
              onClick={() =>
                void run(async () => {
                  const result = await api<{ ok: boolean; detail: string }>(
                    '/api/users/security/whatsapp/check',
                    { method: 'POST' },
                  )
                  setGreenResult(result.detail)
                  setGreenFailed(!result.ok)
                })
              }
            >
              Check account for alerts
            </Button>
            <Button
              type="button"
              disabled={busy || !security.data?.green_api_token_set}
              onClick={() =>
                void run(async () => {
                  const result = await api<{ ok: boolean; detail: string }>(
                    '/api/users/security/whatsapp/test',
                    { method: 'POST' },
                  )
                  setGreenResult(result.detail)
                  setGreenFailed(!result.ok)
                })
              }
            >
              Test saved GreenAPI
            </Button>
          </div>
        </form>
        <p
          role={greenFailed ? 'alert' : 'status'}
          className={`mt-3 text-sm ${greenFailed ? 'text-danger' : ''}`}
        >
          {greenResult ||
            (security.data?.green_api?.verified
              ? 'GreenAPI test passed.'
              : 'GreenAPI has not passed its test.')}
        </p>
      </section>
    </div>
  )
}
