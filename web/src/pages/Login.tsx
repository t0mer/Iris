import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { IrisMark } from '../components/IrisMark'
import { LanguageSelect } from '../components/LanguageSelect'
import { Button } from '../components/ui/button'
import { Field, Input } from '../components/ui/field'
import { api, ApiError } from '../lib/api'
import { t } from '../lib/i18n'

function explain(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) return t('login.tooManyAttempts')
  if (err instanceof ApiError && err.status === 401) return t('login.wrongCredentials')
  return t('login.couldNotReach')
}

export function Login() {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    document.title = t('login.title')
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
      await qc.invalidateQueries({ queryKey: ['me'] })
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto grid min-h-dvh w-full max-w-sm content-center gap-8 px-6 py-10">
      <LanguageSelect />
      <div className="flex flex-col items-center gap-3 text-center text-primary">
        <IrisMark className="size-14" />
        <div className="flex flex-col gap-1 text-foreground">
          <h1 className="text-3xl font-semibold tracking-tight">{t('layout.appName')}</h1>
          <p className="text-sm text-muted-foreground">{t('login.tagline')}</p>
        </div>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl border bg-surface p-6">
        <Field label={t('login.username')}>
          <Input
            dir="ltr"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </Field>
        <Field label={t('login.password')}>
          <Input
            type="password"
            dir="ltr"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {error && (
          <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" disabled={busy}>
          {busy && <Loader2 className="animate-spin" />} {t('login.signIn')}
        </Button>
      </form>
    </main>
  )
}
