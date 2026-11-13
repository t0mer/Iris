import { t } from '../lib/i18n'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '../lib/notify'
import { api } from '../lib/api'
import { Button } from '../components/ui/button'
import { Field, Input, Select } from '../components/ui/field'
import { Section } from '../components/Section'
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
      await qc.invalidateQueries({ queryKey: ['recipient-channels'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-6">
      <Section collapsible title={t('SMTP server')}>
        <p className="mb-4 text-sm text-muted-foreground">
          {t(
            'This SMTP server delivers email alerts and sign-in codes. Enter its host, port, TLS mode and credentials. Configure your admin email in Settings → Users, then save and send a test. Open its approval link to approve the email for 2FA. Approval links use Iris base URL in Settings → Notifications.',
          )}
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
          <Field label={t('SMTP provider')}>
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
              <option value="custom">{t('Custom SMTP / other provider')}</option>
              <option value="gmail">Gmail</option>
            </Select>
          </Field>
          <Field label={t('SMTP host')}>
            <Input
              required
              value={smtp.host}
              onChange={(e) => setSMTP({ ...smtp, host: e.target.value })}
            />
          </Field>
          <Field label={t('Port')}>
            <Input
              type="number"
              required
              min={1}
              max={65535}
              value={smtp.port}
              onChange={(e) => setSMTP({ ...smtp, port: Number(e.target.value) })}
            />
          </Field>
          <Field label={t('Security')}>
            <Select value={smtp.tls} onChange={(e) => setSMTP({ ...smtp, tls: e.target.value })}>
              <option value="starttls">STARTTLS</option>
              <option value="ssl">SSL / TLS</option>
            </Select>
          </Field>
          <Field label={t('SMTP username')}>
            <Input
              required
              value={smtp.username}
              onChange={(e) => setSMTP({ ...smtp, username: e.target.value })}
            />
          </Field>
          <Field label={t('SMTP password')}>
            <Input
              type="password"
              value={smtp.password}
              autoComplete="new-password"
              placeholder={security.data?.password_set ? t('Saved (leave blank to keep)') : ''}
              onChange={(e) => setSMTP({ ...smtp, password: e.target.value })}
            />
          </Field>
          <Field label={t('Sender email')}>
            <Input
              type="email"
              required
              value={smtp.sender}
              onChange={(e) => setSMTP({ ...smtp, sender: e.target.value })}
            />
          </Field>
          <Button type="submit" variant="primary" disabled={busy || security.data?.enabled}>
            {t('Save SMTP')}
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
            {t('Test saved SMTP')}
          </Button>
        </form>
        {smtp.host === 'smtp.gmail.com' && (
          <p className="mt-3 text-sm text-muted-foreground">
            {t(
              'Gmail uses your full email username and a Google app password. Choose STARTTLS port 587 or SSL / TLS port 465.',
            )}
          </p>
        )}
        <p
          role={smtpFailed ? 'alert' : 'status'}
          className={`mt-3 text-sm ${smtpFailed ? 'text-danger' : ''}`}
        >
          {result ||
            (security.data?.smtp.verified
              ? t('SMTP test passed.')
              : t('SMTP has not passed its test.'))}
        </p>
      </Section>
      <Section collapsible title="GreenAPI">
        <p className="mb-4 text-sm text-muted-foreground">
          {t(
            'GreenAPI sends parent alerts and sign-in codes through WhatsApp. Save your credentials and check the account, then select GreenAPI for each parent in Alert delivery. Parent alerts support individual numbers and group IDs. To use GreenAPI for two-factor authentication, test delivery to your personal number configured in Settings → Users and open the approval link. Sign-in codes are sent only to personal numbers.',
          )}
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
          <Field label={t('GreenAPI API URL')}>
            <Input
              required
              type="url"
              value={green.api_url}
              onChange={(e) => setGreen({ ...green, api_url: e.target.value })}
            />
          </Field>
          <Field
            label={t('GreenAPI media URL')}
            hint={t(
              'Optional media endpoint from your GreenAPI account. Text alerts use the API URL.',
            )}
          >
            <Input
              type="url"
              value={green.media_url ?? ''}
              onChange={(e) => setGreen({ ...green, media_url: e.target.value })}
            />
          </Field>
          <Field label={t('GreenAPI instance ID')}>
            <Input
              required
              inputMode="numeric"
              value={green.instance_id}
              onChange={(e) => setGreen({ ...green, instance_id: e.target.value })}
            />
          </Field>
          <Field label={t('GreenAPI API token')}>
            <Input
              type="password"
              autoComplete="new-password"
              required={!security.data?.green_api_token_set}
              placeholder={
                security.data?.green_api_token_set ? t('Saved — leave blank to keep') : ''
              }
              value={green.token}
              onChange={(e) => setGreen({ ...green, token: e.target.value })}
            />
          </Field>
          <div className="flex flex-wrap items-end gap-2">
            <Button type="submit" variant="primary" disabled={busy || security.data?.enabled}>
              {t('Save GreenAPI')}
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
              {t('Check account for alerts')}
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
              {t('Test saved GreenAPI')}
            </Button>
          </div>
        </form>
        <p
          role={greenFailed ? 'alert' : 'status'}
          className={`mt-3 text-sm ${greenFailed ? 'text-danger' : ''}`}
        >
          {greenResult ||
            (security.data?.green_api?.verified
              ? t('GreenAPI test passed.')
              : t('GreenAPI has not passed its test.'))}
        </p>
      </Section>
    </div>
  )
}
