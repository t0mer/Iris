import { useLayoutEffect, useSyncExternalStore } from 'react'
import { locales, isLanguage, type Language } from './locales'

export type { Language } from './locales'
export type LanguagePreference = Language | 'system'
export const LANGUAGE_KEY = 'iris.language'
const LANGUAGE_EVENT = 'iris:language'
let memoryPreference: LanguagePreference | undefined
let loginSelection: LanguagePreference | undefined
let account: { id: number; language: LanguagePreference } | null = null

export function getLanguageUserId() {
  return account?.id
}

export function takeLoginLanguageSelection() {
  const selection = loginSelection
  loginSelection = undefined
  return selection
}

export function setAccountLanguage(user: { id: number; language?: string } | null) {
  const language = isLanguage(user?.language) ? user.language : 'system'
  if (account?.id === user?.id && (!user || account?.language === language)) return
  account = user ? { id: user.id, language } : null
  applyLanguage()
  window.dispatchEvent(new Event(LANGUAGE_EVENT))
}

/** Only the browser's preferred language selects the initial UI language. */
export function browserLanguage(languages: readonly string[]): Language {
  const primary = (languages[0] ?? '').toLowerCase().split(/[-_]/)[0]
  const language = primary === 'iw' ? 'he' : primary
  return isLanguage(language) ? language : 'en'
}

export function getLanguagePreference(): LanguagePreference {
  if (account) return account.language
  if (memoryPreference) return memoryPreference
  try {
    const stored = localStorage.getItem(LANGUAGE_KEY)
    if (isLanguage(stored)) return stored
  } catch {
    // Language selection also works when browser storage is unavailable.
  }
  return 'system'
}

export function getLanguage(): Language {
  const preference = getLanguagePreference()
  return preference === 'system'
    ? browserLanguage(navigator.languages?.length ? navigator.languages : [navigator.language])
    : preference
}

export function applyLanguage() {
  const language = getLanguage()
  document.documentElement.lang = language
  document.documentElement.dir = locales[language].dir
}

export function setLanguage(preference: LanguagePreference) {
  loginSelection = preference
  memoryPreference = undefined
  try {
    if (preference === 'system') localStorage.removeItem(LANGUAGE_KEY)
    else localStorage.setItem(LANGUAGE_KEY, preference)
  } catch {
    memoryPreference = preference
  }
  applyLanguage()
  window.dispatchEvent(new Event(LANGUAGE_EVENT))
}

function subscribe(notify: () => void) {
  const changed = () => {
    applyLanguage()
    notify()
  }
  const storageChanged = (event: StorageEvent) => {
    if (event.key === LANGUAGE_KEY || event.key === null) changed()
  }
  window.addEventListener(LANGUAGE_EVENT, changed)
  window.addEventListener('languagechange', changed)
  window.addEventListener('storage', storageChanged)
  return () => {
    window.removeEventListener(LANGUAGE_EVENT, changed)
    window.removeEventListener('languagechange', changed)
    window.removeEventListener('storage', storageChanged)
  }
}

export function useLanguage() {
  const language = useSyncExternalStore(subscribe, getLanguage)
  const preference = useSyncExternalStore(subscribe, getLanguagePreference)
  useLayoutEffect(applyLanguage, [language])
  return { language, preference, dir: locales[language].dir }
}

/** English source text is also the fallback for untranslated provider messages. */
const sentenceTemplates = Object.keys(locales.en.messages)
  .filter((key) => /\{\w+\}/.test(key))
  .map((key) => {
    const names = [...key.matchAll(/\{(\w+)\}/g)].map((match) => match[1])
    const fragments = key.split(/\{\w+\}/)
    const escaped = fragments.map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    return {
      key,
      names,
      prefix: fragments[0],
      expression: new RegExp('^' + escaped.join('([\\s\\S]*?)') + '$'),
    }
  })

export function t(
  text: string,
  values?: Record<string, string | number | boolean | null | undefined>,
): string {
  const language = getLanguage()
  let translated = locales[language].messages[text] ?? locales.en.messages[text]
  if (translated === undefined && language !== 'en') {
    for (const template of sentenceTemplates) {
      if (!text.startsWith(template.prefix)) continue
      const match = template.expression.exec(text)
      if (!match || match.slice(1).some((value) => /[.!?]\s+[A-Z]/.test(value))) continue
      translated = locales[language].messages[template.key] ?? template.key
      values = Object.fromEntries(template.names.map((name, index) => [name, match[index + 1]]))
      break
    }
  }
  if (translated === undefined && language !== 'en') {
    const field = /^([a-z_]+(?:\.[a-z_]+)+): (.+)$/.exec(text)
    if (field) return `${t(field[1])}: ${t(field[2])}`
    const sentences = text.split(/(?<=[.!?])\s+(?=[A-Z])/)
    if (sentences.length > 1) return sentences.map((sentence) => t(sentence)).join(' ')
  }
  translated ??= text
  return values
    ? translated.replace(/\{(\w+)\}/g, (token, key: string) => String(values[key] ?? token))
    : translated
}
