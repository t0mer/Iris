import { t } from '../lib/i18n'
import { RepairPhone } from './RepairPhone'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Instance } from '../lib/types'
import { Dialog, DialogTrigger, DialogContent } from './ui/dialog'
import { Button } from './ui/button'
import { Field, Input, Select } from './ui/field'

export function EditPhone({ phone }: { phone: Instance }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const initial = () => ({
    kid_name: phone.kid_name,
    role: phone.role || 'child',
    enabled: phone.enabled,
    phone_number: phone.phone_number || '',
    openwa_base_url: phone.openwa_base_url,
    openwa_instance_id: phone.openwa_instance_id,
    openwa_api_key: '',
    session_name: phone.session_name || '',
  })
  const [form, setForm] = useState(initial)
  const save = useMutation({
    mutationFn: () =>
      api(`/api/instances/${phone.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          ...form,
          phone_number: form.phone_number || null,
          enabled: form.role === 'parent' ? false : form.enabled,
          verify_openwa:
            form.openwa_base_url !== phone.openwa_base_url ||
            form.openwa_instance_id !== phone.openwa_instance_id ||
            Boolean(form.openwa_api_key),
        }),
      }),
    onSuccess: () => {
      setOpen(false)
      void qc.invalidateQueries({ queryKey: ['stats'] })
      return qc.invalidateQueries({ queryKey: ['instances'] })
    },
  })
  const field = (
    key:
      | 'kid_name'
      | 'phone_number'
      | 'openwa_base_url'
      | 'openwa_instance_id'
      | 'openwa_api_key'
      | 'session_name',
  ) => ({
    value: form[key],
    onChange: (event: { target: { value: string } }) =>
      setForm({ ...form, [key]: event.target.value }),
  })
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (save.isPending) return
        if (value) {
          setForm(initial())
          save.reset()
        }
        setOpen(value)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">{t('Edit phone')}</Button>
      </DialogTrigger>
      <DialogContent
        title={t('Edit {value0}', { value0: phone.kid_name })}
        description={t('Update this Iris connection. OpenWA credentials are checked when changed.')}
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            save.mutate()
          }}
        >
          <Field label={t('Display name')}>
            <Input required {...field('kid_name')} />
          </Field>
          <Field
            label={t('Session name in Iris')}
            hint={t(
              'An Iris label only. This OpenWA version does not support renaming its session through the API.',
            )}
          >
            <Input {...field('session_name')} maxLength={100} />
          </Field>
          <Field label={t('Phone role')}>
            <Select
              value={form.role}
              onChange={(event) =>
                setForm({ ...form, role: event.target.value as 'child' | 'parent' })
              }
            >
              <option value="child">{t('Child')}</option>
              <option value="parent">{t('Parent alert sender')}</option>
            </Select>
          </Field>
          {form.role === 'child' && (
            <label className="flex min-h-11 items-center gap-3">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
              />
              {t('Monitor this child')}
            </label>
          )}
          <Field label={t('OpenWA address')}>
            <Input required type="url" dir="ltr" {...field('openwa_base_url')} />
          </Field>
          <Field
            label={t('OpenWA session ID')}
            hint={t('OpenWA-generated ID. Changing it selects a different existing session.')}
          >
            <Input required dir="ltr" {...field('openwa_instance_id')} />
          </Field>
          <Field
            label={t('OpenWA API key')}
            hint={t('Leave blank to keep the stored key. A new address requires a new key.')}
          >
            <Input type="password" autoComplete="new-password" {...field('openwa_api_key')} />
          </Field>
          <Field label={t('Phone number')}>
            <Input type="tel" dir="ltr" {...field('phone_number')} />
          </Field>
          {save.isError && (
            <p role="alert" className="text-sm text-danger">
              {save.error instanceof Error ? save.error.message : t('Changes could not be saved.')}
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            {t('After changing a child’s OpenWA session, register its webhook again.')}
          </p>
          <RepairPhone phone={phone} />
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? t('Saving…') : t('Save changes')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
