import { hebrew } from './he'
import { hebrewFeedback } from './he-feedback'
import { hebrewDynamic } from './he-dynamic'
import { hebrewServer } from './he-server'
import languageMetadata from '../../../../app/assets/ui-languages.json'

export const english: Record<string, string> = Object.fromEntries(
  Object.keys({ ...hebrew, ...hebrewFeedback, ...hebrewDynamic, ...hebrewServer }).map((key) => [
    key,
    key,
  ]),
)

/** Register another language here with its native name, direction and complete catalogue. */
export const locales = {
  en: { ...languageMetadata.en, dir: 'ltr', messages: english },
  he: {
    ...languageMetadata.he,
    dir: 'rtl',
    messages: { ...hebrew, ...hebrewFeedback, ...hebrewDynamic, ...hebrewServer } as Record<
      string,
      string
    >,
  },
} as const satisfies Record<
  keyof typeof languageMetadata,
  { nativeName: string; dir: 'ltr' | 'rtl'; messages: Record<string, string> }
>

export type Language = keyof typeof locales
export function isLanguage(value: string | null | undefined): value is Language {
  return value !== undefined && value !== null && Object.hasOwn(locales, value)
}
