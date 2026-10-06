import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * List filters live in the address, so links from the dashboard work and the back button behaves.
 * Updates are functional: they apply to the newest address, so a delayed change (like the debounced
 * search) can never revert a filter the user changed in the meantime.
 */
export function useUrlState() {
  const [sp, setSp] = useSearchParams()
  const get = (k: string) => sp.get(k) ?? ''
  // A hand-edited or stale ?page= must never become NaN or a negative page.
  const page = Math.max(1, Number.parseInt(sp.get('page') ?? '1', 10) || 1)
  const update = useCallback(
    (changes: Record<string, string>) =>
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(changes)) {
            if (v) next.set(k, v)
            else next.delete(k)
          }
          if (!('page' in changes)) next.delete('page') // any filter change starts from page one
          return next
        },
        { replace: true },
      ),
    [setSp],
  )
  const clear = useCallback(() => setSp(new URLSearchParams(), { replace: true }), [setSp])
  return { get, page, update, clear }
}
