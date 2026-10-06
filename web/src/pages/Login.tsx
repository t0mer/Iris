import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { IrisMark } from '../components/IrisMark'
import { Button } from '../components/ui/button'
import { Field, Input } from '../components/ui/field'
import { api, ApiError } from '../lib/api'

function explain(err: unknown): string {
  if (err instanceof ApiError && err.status === 429)
    return 'Too many failed attempts. Wait a few minutes, then try again.'
  if (err instanceof ApiError && err.status === 401)
    return 'That username and password do not match. Check them and try again.'
  return 'Could not reach Iris. Check your connection and try again.'
}

export function Login() {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    document.title = 'Sign in · Iris'
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
      <div className="flex flex-col items-center gap-3 text-center text-primary">
        <IrisMark className="size-14" />
        <div className="flex flex-col gap-1 text-foreground">
          <h1 className="text-3xl font-semibold tracking-tight">Iris</h1>
          <p className="text-sm text-muted-foreground">
            Sign in to see how your kids' chats are doing.
          </p>
        </div>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl border bg-surface p-6">
        <Field label="Username">
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
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
          {busy && <Loader2 className="animate-spin" />} Sign in
        </Button>
      </form>
    </main>
  )
}
