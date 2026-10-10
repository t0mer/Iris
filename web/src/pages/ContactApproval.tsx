import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { Button } from '../components/ui/button'

export function ContactApproval() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [busy, setBusy] = useState(false)
  const [approved, setApproved] = useState(false)
  const [error, setError] = useState('')
  return (
    <main className="mx-auto mt-12 max-w-md rounded-lg border bg-surface p-6">
      <h1 className="mb-3 text-xl font-semibold">Approve your Iris contact</h1>
      <p className="mb-4">
        {approved
          ? 'Your contact is approved for alerts and two-factor authentication. Your administrator can now select you as an alert recipient.'
          : 'Confirm that this email address, WhatsApp number or Telegram destination belongs to you. This link expires after 30 minutes.'}
      </p>
      {error && (
        <p role="alert" className="mb-3 text-danger">
          {error}
        </p>
      )}
      {!approved && (
        <Button
          disabled={busy || !token}
          onClick={async () => {
            setBusy(true)
            setError('')
            try {
              await api('/api/auth/confirm-contact', {
                method: 'POST',
                body: JSON.stringify({ token }),
              })
              setApproved(true)
              window.history.replaceState(null, '', '/verify-contact')
            } catch (error) {
              setError(error instanceof Error ? error.message : 'Could not approve contact')
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Approving…' : 'Approve contact'}
        </Button>
      )}
      <Link className="mt-4 block underline" to="/">
        Return to Iris
      </Link>
    </main>
  )
}
