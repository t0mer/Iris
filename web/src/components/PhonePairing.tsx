import { t } from '../lib/i18n'
import { LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { api } from '../lib/api'
import { Button } from './ui/button'

export interface PairingState {
  token: string
  session_name?: string
  session_id: string
  status: string
  qr: string | null
  phone_number?: string | null
  qr_valid_seconds?: number
}

export function PhonePairing({
  url,
  apiKey,
  name,
  onChange,
  savedToken,
}: {
  url?: string
  name?: string
  apiKey?: string
  onChange: (state: PairingState | null) => void
  savedToken: MutableRefObject<string | null>
}) {
  const [state, setState] = useState<PairingState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const startedAt = useRef(0)
  const token = useRef<string | null>(null)
  const alive = useRef(true)
  const fetching = useRef(false)
  const refreshRequested = useRef(false)
  const retiredQr = useRef<string | null>(null)
  const current = useRef<PairingState | null>(null)
  const changed = useRef(onChange)
  useEffect(() => {
    changed.current = onChange
  }, [onChange])

  function update(next: PairingState | null) {
    current.current = next
    setState(next)
    changed.current(next)
  }

  useEffect(() => {
    alive.current = true
    const cancel = () => {
      const value = token.current
      if (value && savedToken.current !== value) {
        void fetch(`/api/pairing/${value}`, {
          method: 'DELETE',
          credentials: 'same-origin',
          keepalive: true,
        }).catch(() => {})
      }
    }
    window.addEventListener('pagehide', cancel)
    return () => {
      alive.current = false
      window.removeEventListener('pagehide', cancel)
      cancel()
    }
  }, [savedToken])

  async function poll(refresh = false) {
    const value = token.current
    if (!value) return
    if (refresh) {
      if (current.current?.qr) retiredQr.current = current.current.qr
      update(current.current ? { ...current.current, qr: null, status: 'waiting' } : null)
    }
    if (fetching.current) {
      if (refresh) refreshRequested.current = true
      return
    }
    fetching.current = true
    try {
      const next = await api<Omit<PairingState, 'token'>>(
        `/api/pairing/${value}${refresh ? '/refresh' : ''}`,
        refresh ? { method: 'POST' } : undefined,
      )
      if (!alive.current || token.current !== value) return
      update({
        ...next,
        token: value,
        ...(next.qr && next.qr === retiredQr.current ? { qr: null, status: 'waiting' } : {}),
      })
      setError('')
    } catch (err) {
      if (alive.current && token.current === value) {
        update(current.current ? { ...current.current, qr: null, status: 'error' } : null)
        setError(
          err instanceof Error ? err.message : 'OpenWA connection failed. No QR is available.',
        )
      }
    } finally {
      fetching.current = false
      if (refreshRequested.current && alive.current && token.current) {
        refreshRequested.current = false
        void poll(true)
      }
    }
  }

  useEffect(() => {
    if (!state?.token) return
    const timer = window.setInterval(() => {
      void poll()
    }, 2000)
    return () => window.clearInterval(timer)
  }, [state?.token])

  const waiting = Boolean(
    state && !state.qr && !['ready', 'error', 'canceling'].includes(state.status),
  )
  useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)),
      1000,
    )
    return () => window.clearInterval(timer)
  }, [waiting])

  async function start() {
    setBusy(true)
    setError('')
    startedAt.current = Date.now()
    setElapsed(0)
    update({ token: '', session_id: '', status: 'starting', qr: null })
    try {
      const next = await api<PairingState>('/api/pairing', {
        method: 'POST',
        body: JSON.stringify({
          ...(name?.trim() ? { name: name.trim() } : {}),
          ...(url && apiKey ? { openwa_base_url: url, openwa_api_key: apiKey } : {}),
        }),
      })
      if (!alive.current) {
        void fetch(`/api/pairing/${next.token}`, {
          method: 'DELETE',
          credentials: 'same-origin',
          keepalive: true,
        }).catch(() => {})
        return
      }
      token.current = next.token
      update(next)
      await poll()
    } catch (err) {
      if (alive.current) {
        update(null)
        setError(
          err instanceof Error ? err.message : 'OpenWA connection failed. No QR is available.',
        )
      }
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  async function cancel() {
    setBusy(true)
    update(current.current ? { ...current.current, qr: null, status: 'canceling' } : null)
    try {
      await api(`/api/pairing/${token.current}`, { method: 'DELETE' })
      token.current = null
      update(null)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cleanup failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-md border bg-surface-2 p-3">
      <h3 className="font-semibold">{t('Pair a new phone with QR')}</h3>
      <p className="text-sm text-muted-foreground">
        {t(
          'Get the QR code and link WhatsApp first. You can add an optional name after pairing. Iris uses the server’s configured OpenWA connection.',
        )}
      </p>
      {!state?.token && (
        <Button
          onClick={() => void start()}
          disabled={busy || (name === undefined && (!url || !apiKey))}
        >
          {busy ? t('Connecting to OpenWA…') : t('Get pairing QR')}
        </Button>
      )}
      {waiting && (
        <div className="flex flex-col gap-2 rounded-md border bg-surface p-3">
          <div role="status" className="flex items-start gap-2">
            <LoaderCircle
              aria-hidden
              className="mt-0.5 size-5 shrink-0 animate-spin motion-reduce:animate-none"
            />
            <span>
              {state?.status === 'starting'
                ? t('Pairing started. Creating and starting your OpenWA session…')
                : state?.status === 'authenticating'
                  ? t('Scan received. Waiting for WhatsApp to confirm the connection…')
                  : state?.status === 'initializing'
                    ? t('OpenWA is starting WhatsApp. Waiting for the QR code…')
                    : t('Session started. Waiting for OpenWA to generate a QR code…')}
            </span>
          </div>
          <progress aria-label={t('Waiting for WhatsApp pairing')} className="h-2 w-full" />
          <p className="text-xs text-muted-foreground">
            {t('Elapsed:')} {elapsed}
            {t('s. Iris checks for updates every 2 seconds.')}
          </p>
          {elapsed >= 20 && (
            <p className="text-sm text-muted-foreground">
              {t(
                'OpenWA is taking longer to respond. Keep this window open; the QR will appear automatically when available.',
              )}
            </p>
          )}
        </div>
      )}
      {state?.qr && (
        <img
          src={state.qr}
          alt="WhatsApp pairing QR code"
          onError={() => {
            setError('QR image could not be displayed. Requesting a fresh code…')
            void poll(true)
          }}
          className="mx-auto aspect-square w-full max-w-64 rounded-md bg-white p-2"
        />
      )}
      {state?.token && (
        <>
          {!waiting && (
            <p role="status">
              {state.status === 'ready'
                ? t('WhatsApp connected. Iris is saving this phone automatically.')
                : state.status === 'qr_ready'
                  ? t('WhatsApp → Linked devices → Link a device. QR refreshes automatically.')
                  : state.status === 'error'
                    ? t('OpenWA unavailable. The QR has been removed.')
                    : t('Waiting for OpenWA to provide a fresh QR or confirm the connection…')}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void poll(true)} disabled={busy || state.status === 'ready'}>
              {t('Refresh QR')}
            </Button>
            <Button onClick={() => void cancel()} disabled={busy}>
              {t('Cancel pairing')}
            </Button>
          </div>
        </>
      )}
      {error && (
        <p role="alert" className="break-words text-sm text-danger">
          {error}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {t(
          'Closing before pairing is saved removes the temporary OpenWA session. After Iris saves the paired phone, closing the optional name step keeps the connection. If a connection is lost, server cleanup retries after the pairing lease expires. Existing sessions are never removed.',
        )}
      </p>
    </section>
  )
}
