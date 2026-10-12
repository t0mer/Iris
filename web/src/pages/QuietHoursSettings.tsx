import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import { toast } from '../lib/notify'
import { Button } from '../components/ui/button'
import { Field, Input } from '../components/ui/field'

type Quiet = { enabled: boolean; start: string; end: string }
type Draft = { parent: Quiet; system: Quiet }
const defaults: Quiet = { enabled: false, start: '22:00', end: '07:00' }

export function QuietHoursSettings({ settings }: { settings: Record<string, unknown> }) {
  const [draft, setDraft] = useState<Draft | null>(null)
  const qc = useQueryClient()
  const values: Draft = draft ?? {
    parent: (settings['alerts.parent_quiet_hours'] as Quiet | undefined) ?? defaults,
    system: (settings['alerts.system_quiet_hours'] as Quiet | undefined) ?? defaults,
  }
  const update = (scope: keyof Draft, changes: Partial<Quiet>) =>
    setDraft({ ...values, [scope]: { ...values[scope], ...changes } })
  const save = useMutation({
    mutationFn: () =>
      api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          settings: {
            'alerts.parent_quiet_hours': values.parent,
            'alerts.system_quiet_hours': values.system,
          },
        }),
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['settings'] })
      setDraft(null)
      toast.success(t('Quiet hours saved.'))
    },
    onError: (error) => toast.error(error.message),
  })
  const invalid = (['parent', 'system'] as const).some(
    (scope) => values[scope].start === values[scope].end,
  )
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <h3 className="font-semibold">{t('Quiet hours')}</h3>
      <p className="text-sm text-muted-foreground">
        {t(
          'Parent and system notifications have separate quiet hours. Notifications wait in the persistent queue and resume when quiet hours end. Sign-in codes and connection tests remain immediate.',
        )}
      </p>
      <p className="text-sm">
        {t('Time zone')}: <bdi>{String(settings['alerts.timezone'] || 'Asia/Jerusalem')}</bdi>
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {(['parent', 'system'] as const).map((scope) => (
          <fieldset key={scope} className="min-w-0 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">
              {t(scope === 'parent' ? 'Parent notifications' : 'System notifications')}
            </legend>
            <label className="mb-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={values[scope].enabled}
                disabled={save.isPending}
                onChange={(event) => update(scope, { enabled: event.target.checked })}
              />
              {t('Enable quiet hours')}
            </label>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('Quiet hours start')}>
                <Input
                  type="time"
                  dir="ltr"
                  value={values[scope].start}
                  disabled={!values[scope].enabled || save.isPending}
                  onChange={(event) => update(scope, { start: event.target.value })}
                />
              </Field>
              <Field label={t('Quiet hours end')}>
                <Input
                  type="time"
                  dir="ltr"
                  value={values[scope].end}
                  disabled={!values[scope].enabled || save.isPending}
                  onChange={(event) => update(scope, { end: event.target.value })}
                />
              </Field>
            </div>
          </fieldset>
        ))}
      </div>
      {invalid && (
        <p role="alert" className="text-sm text-danger">
          {t('Quiet hours must have different start and end times.')}
        </p>
      )}
      <div className="flex gap-2">
        <Button disabled={!draft || invalid || save.isPending} onClick={() => save.mutate()}>
          {t('Save quiet hours')}
        </Button>
        {draft && (
          <Button variant="ghost" disabled={save.isPending} onClick={() => setDraft(null)}>
            {t('Cancel')}
          </Button>
        )}
      </div>
    </div>
  )
}
