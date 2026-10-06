import { useSyncExternalStore } from 'react'

export type Theme = 'system' | 'light' | 'dark'
const KEY = 'iris-theme'
const QUERY = '(prefers-color-scheme: dark)'

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system' // storage can be blocked (private windows)
  }
}

export function applyTheme(theme: Theme = getTheme()): void {
  const prefersDark = window.matchMedia?.(QUERY).matches ?? false
  const dark = theme === 'dark' || (theme === 'system' && prefersDark)
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(theme: Theme): void {
  try {
    if (theme === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, theme)
  } catch {
    // the choice still applies for this page view
  }
  applyTheme(theme)
}

/** Follow the operating system while the theme is "system". */
export function watchSystemTheme(): void {
  window.matchMedia?.(QUERY).addEventListener?.('change', () => {
    if (getTheme() === 'system') applyTheme('system')
  })
}

/** True while the page is in dark mode, following the toggle and the system preference. */
export function useIsDark(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const observer = new MutationObserver(notify)
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
      return () => observer.disconnect()
    },
    () => document.documentElement.classList.contains('dark'),
    () => false,
  )
}
