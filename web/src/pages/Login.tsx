import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { IrisMark } from '../components/IrisMark'
import { Button } from '../components/ui/button'
import { Field, Input } from '../components/ui/field'
import { api, ApiError } from '../lib/api'

function explain(err: unknown): string {
  if (err instanceof ApiError && err.status === 408) return err.message
  if (
    err instanceof ApiError &&
    err.status === 429 &&
    (err.message.includes('WhatsApp code limit') || err.message.includes('code requests'))
  )
    return err.message
  if (err instanceof ApiError && err.status === 429)
    return 'Too many failed attempts. Wait a few minutes, then try again.'
  if (err instanceof ApiError && (err.status === 403 || err.status === 422)) return err.message
  if (err instanceof ApiError && err.status === 401)
    return 'That username and password do not match. Check them and try again.'
  return 'Could not reach Iris. Check your connection and try again.'
}

export function Login() {
  const qc = useQueryClient()
  const [challenge, setChallenge] = useState('')
  const [code, setCode] = useState('')
  const [channel, setChannel] = useState('')
  const { data: options } = useQuery({
    queryKey: ['login-options'],
    queryFn: () =>
      api<{
        two_factor_enabled: boolean
        default_channel?: string
        secure_login_url?: string | null
      }>('/api/auth/options'),
  })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const [accepted, setAccepted] = useState(false)
  const needsHttps = window.location.protocol === 'http:' && !!options?.secure_login_url
  useEffect(() => {
    document.title = 'Sign in · Iris'
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (submitting.current || needsHttps) return
    submitting.current = true
    setError(null)
    setBusy(true)
    try {
      if (accepted) {
        // Retry session loading without consuming the accepted code a second time.
      } else if (challenge) {
        await api('/api/auth/verify', {
          method: 'POST',
          body: JSON.stringify({ challenge_id: challenge, code }),
        })
      } else {
        const result = await api<{ challenge_id?: string; channel?: string }>('/api/auth/login', {
          method: 'POST',
          body: JSON.stringify({
            username,
            password,
            ...(options?.two_factor_enabled
              ? { channel: channel || options?.default_channel || 'email' }
              : {}),
          }),
        })
        if (result.challenge_id) {
          setChallenge(result.challenge_id)
          setPassword('')
          return
        }
      }
      setAccepted(true)
      try {
        const me = await api('/api/auth/me')
        qc.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
        qc.setQueryData(['me'], me)
      } catch (err) {
        setError(
          err instanceof ApiError && err.status === 408
            ? 'Sign-in was accepted, but loading your session timed out. Click Retry session.'
            : 'Your code was accepted, but the browser could not establish a session. Open Iris using its HTTPS address and sign in again.',
        )
      }
    } catch (err) {
      if (challenge && err instanceof ApiError && err.status === 408) {
        // A timed-out verification may have consumed the code on the server.
        // Recover the session or request a fresh code, never replay this code.
        setAccepted(true)
        setError(
          'Verification timed out. Click Retry session to check whether you are signed in, or request another code.',
        )
        return
      }
      setError(
        challenge && err instanceof ApiError && err.status === 401
          ? err.message
          : err instanceof ApiError &&
              (err.status === 403 || err.status === 422 || err.status === 503)
            ? err.message
            : explain(err),
      )
    } finally {
      setBusy(false)
      submitting.current = false
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
        {needsHttps && (
          <p role="alert">
            Sign in using the HTTPS address so your browser can save the secure session cookie.{' '}
            <a className="underline" href={options.secure_login_url!}>
              Open secure Iris
            </a>
          </p>
        )}
        {!challenge && (
          <>
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
            {options?.two_factor_enabled && (
              <Field label="Send verification code by">
                <select
                  className="rounded border p-2"
                  value={channel || options?.default_channel || 'email'}
                  onChange={(e) => setChannel(e.target.value)}
                >
                  <option value="email">Email</option>
                  <option value="whatsapp">GreenAPI / WhatsApp</option>
                </select>
              </Field>
            )}
          </>
        )}
        {challenge && (
          <>
            <p className="text-sm">
              Enter the code sent to your configured contact. It expires in 5 minutes.
            </p>
            <Field label="Verification code">
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
                onPaste={(e) => {
                  e.preventDefault()
                  setCode(
                    e.clipboardData
                      .getData('text')
                      .replace(/[^0-9]/g, '')
                      .slice(0, 6),
                  )
                }}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                autoFocus
              />
            </Field>
            <Button
              type="button"
              disabled={busy}
              onClick={() => {
                setChallenge('')
                setCode('')
                setError(null)
                setAccepted(false)
              }}
            >
              Start again / request another code
            </Button>
          </>
        )}
        {busy && (
          <div role="status" className="space-y-2 text-sm text-muted-foreground">
            <p>
              {accepted
                ? 'Loading your session…'
                : challenge
                  ? 'Verifying your code…'
                  : 'Signing in…'}
            </p>
            <div
              role="progressbar"
              aria-label="Sign-in progress"
              className="h-1 animate-pulse rounded bg-primary motion-reduce:animate-none"
            />
          </div>
        )}
        {error && (
          <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
            {error}
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          disabled={busy || (accepted && !error) || needsHttps}
        >
          {busy && <Loader2 className="animate-spin" />}{' '}
          {accepted && error ? 'Retry session' : challenge ? 'Verify code' : 'Sign in'}
        </Button>
      </form>
    </main>
  )
}
