import { useSyncExternalStore } from 'react'

/** True while the media query matches. Defaults to false where matchMedia is unavailable. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mql = window.matchMedia?.(query)
      mql?.addEventListener?.('change', notify)
      return () => mql?.removeEventListener?.('change', notify)
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  )
}

export const useIsDesktop = () => useMediaQuery('(min-width: 768px)')
export const useIsWide = () => useMediaQuery('(min-width: 1024px)')
