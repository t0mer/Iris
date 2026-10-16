/** Browser-local UI preference. Changing it reloads module-level labels consistently. */
export type Language = 'en' | 'he'
export const LANGUAGE_KEY = 'iris-language'

export function getLanguage(): Language {
  try {
    return localStorage.getItem(LANGUAGE_KEY) === 'he' ? 'he' : 'en'
  } catch {
    return 'en'
  }
}

export const language = getLanguage()
export const locale = language === 'he' ? 'he-IL' : 'en-US'
export const dir = language === 'he' ? 'rtl' : 'ltr'

export function applyLanguage(value: Language = language): void {
  document.documentElement.lang = value
  document.documentElement.dir = value === 'he' ? 'rtl' : 'ltr'
  const manifest = document.querySelector<HTMLLinkElement>('link[rel="manifest"]')
  if (manifest)
    manifest.href = value === 'he' ? '/manifest.he.webmanifest' : '/manifest.webmanifest'
}

export function saveLanguage(value: Language): boolean {
  try {
    localStorage.setItem(LANGUAGE_KEY, value)
  } catch {
    return false
  }
  applyLanguage(value)
  return true
}
