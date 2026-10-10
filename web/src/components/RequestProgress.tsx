import { useEffect, useState, useSyncExternalStore } from 'react'
import { Loader2 } from 'lucide-react'
import { requestActivity } from '../lib/api'

/** Indeterminate progress: the server does not expose a completion percentage. */
export function RequestProgress() {
  const pending = useSyncExternalStore(requestActivity.subscribe, requestActivity.snapshot)
  const active = pending > 0
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (!active) return
    const timer = setTimeout(() => setVisible(true), 300)
    return () => {
      clearTimeout(timer)
      setVisible(false)
    }
  }, [active])
  if (!pending || !visible) return null
  return (
    <div
      role="progressbar"
      aria-label="Iris is working"
      className="fixed inset-x-0 top-0 z-[100] pointer-events-none"
    >
      <div className="h-1 w-full animate-pulse bg-primary motion-reduce:animate-none" />
      <div
        role="status"
        className="mx-auto flex w-fit items-center gap-2 rounded-b-md border bg-surface px-3 py-2 text-sm shadow-sm"
      >
        <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />{' '}
        Working…
      </div>
    </div>
  )
}
