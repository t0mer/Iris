import { Field, Select } from './ui/field'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import type { Me } from '../lib/auth'
import { locales, type Language } from '../lib/locales'
import {
  getLanguageUserId,
  setAccountLanguage,
  setLanguage,
  t,
  useLanguage,
  type LanguagePreference,
} from '../lib/i18n'

export function LanguageSelect({ compact = false }: { compact?: boolean }) {
  const { preference } = useLanguage()
  const qc = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)
  async function choose(language: LanguagePreference) {
    const id = getLanguageUserId()
    if (id === undefined) {
      setLanguage(language)
      return
    }
    setSaving(true)
    setError(false)
    try {
      await api('/api/auth/language', { method: 'PATCH', body: JSON.stringify({ language }) })
      if (getLanguageUserId() !== id) return
      qc.setQueryData<Me>(['me'], (me) => (me?.id === id ? { ...me, language } : me))
      setAccountLanguage({ id, language })
    } catch {
      setError(true)
    } finally {
      setSaving(false)
    }
  }
  const choices = (
    <>
      <option value="system">{t(compact ? 'Browser language' : 'Browser default')}</option>
      {(Object.keys(locales) as Language[]).map((language) => (
        <option key={language} value={language} lang={language}>
          {locales[language].nativeName}
        </option>
      ))}
    </>
  )
  if (compact)
    return (
      <div className="w-36">
        <select
          aria-label={t('Language')}
          value={preference}
          disabled={saving}
          onChange={(event) => void choose(event.target.value as LanguagePreference)}
          className="min-h-11 w-full rounded-md border bg-surface px-2 text-xs"
        >
          {choices}
        </select>
        {error && (
          <span role="alert" className="text-xs text-danger">
            {t('Could not save language. Try again.')}
          </span>
        )}
      </div>
    )
  return (
    <Field label={t('Language')} className="w-full sm:max-w-72">
      <Select
        value={preference}
        disabled={saving}
        onChange={(event) => void choose(event.target.value as LanguagePreference)}
      >
        <option value="system">{t('Browser default')}</option>
        {(Object.keys(locales) as Language[]).map((language) => (
          <option key={language} value={language} lang={language}>
            {locales[language].nativeName}
          </option>
        ))}
      </Select>
      {error && (
        <span role="alert" className="text-danger">
          {t('Could not save language. Try again.')}
        </span>
      )}
    </Field>
  )
}
