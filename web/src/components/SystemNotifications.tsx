import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import { Button } from './ui/button'
import { Field, Input } from './ui/field'
import { ProviderAlertChannel } from './ProviderHealth'

type Account = {
  id: number
  username: string
  role: string
  email: string | null
  whatsapp_number: string | null
}
type Contacts = Record<string, { telegram_chat_id?: string }>

export function SystemNotifications({ settings }: { settings: Record<string, unknown> }) {
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: () => api<Account[]>('/api/users') })
  const [targets, setTargets] = useState(() =>
    String(settings['alerts.system_recipient'] ?? '')
      .split(/[,;\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
  )
  const [contacts, setContacts] = useState<Contacts>(
    () => (settings['alerts.system_contacts'] ?? {}) as Contacts,
  )
  const [channel, setChannel] = useState(() =>
    String(settings['alerts.provider_notification_channel'] ?? 'mixed'),
  )
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  const [failed, setFailed] = useState(false)
  async function save() {
    setBusy(true)
    setResult('')
    try {
      await api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          settings: {
            'alerts.system_recipient': targets.join(', ') || null,
            'alerts.system_contacts': contacts,
            'alerts.provider_notification_channel': channel,
          },
        }),
      })
      await qc.invalidateQueries({ queryKey: ['settings'] })
      setFailed(false)
      setResult('System notification settings saved.')
    } catch (error) {
      setFailed(true)
      setResult(error instanceof Error ? error.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {t(
          'Choose who receives provider outage and recovery notices. These recipients are separate from parent alerts. Leave the list empty to disable system notification delivery.',
        )}
      </p>
      <ProviderAlertChannel value={channel} onChange={setChannel} />
      {channel === 'mixed' && (
        <p className="text-sm text-muted-foreground">
          {t(
            'Choose a channel for system notifications. A separate working provider can report failures of the main sender.',
          )}
        </p>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 font-medium">{t('System alert recipients')}</legend>
        {users.isError && <p role="alert">{t('Could not load users.')}</p>}
        {(Array.isArray(users.data) ? users.data : [])
          .filter((user) => user.role !== 'watch')
          .map((user) => {
            const target = user.email
              ? 'email:' + user.email.toLowerCase()
              : user.whatsapp_number
                ? user.whatsapp_number.replace(/[^0-9]/g, '') + '@c.us'
                : ''
            const selected = targets.includes(target)
            return (
              <div key={user.id} className="rounded-lg border p-3">
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={selected}
                    disabled={!target || busy}
                    onChange={(event) =>
                      setTargets(
                        event.target.checked
                          ? [...targets, target]
                          : targets.filter((item) => item !== target),
                      )
                    }
                  />
                  <span>{user.username}</span>
                </label>
                {!target && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t('Add an email address or phone number in Users first.')}
                  </p>
                )}
                {selected &&
                  (channel === 'telegram' ||
                    (channel === 'mixed' && settings['alerts.channel'] === 'telegram')) && (
                    <Field label={t('Telegram chat ID')} className="mt-3">
                      <Input
                        dir="ltr"
                        value={contacts[target]?.telegram_chat_id ?? ''}
                        onChange={(event) =>
                          setContacts({
                            ...contacts,
                            [target]: { telegram_chat_id: event.target.value },
                          })
                        }
                      />
                    </Field>
                  )}
              </div>
            )
          })}
      </fieldset>
      <Button
        variant="primary"
        disabled={busy || (targets.length > 0 && channel === 'mixed')}
        onClick={() => void save()}
      >
        {t('Save system notifications')}
      </Button>
      {result && (
        <p role={failed ? 'alert' : 'status'} className={failed ? 'text-danger' : 'text-success'}>
          {t(result)}
        </p>
      )}
    </div>
  )
}
