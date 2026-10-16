import { strings as english } from './en'
import { hebrewStrings as hebrew } from './i18n'

function compare(en: unknown, he: unknown, path: string) {
  expect(typeof en, path).toBe(typeof he)
  if (typeof en === 'string') {
    expect(en, path).not.toMatch(/[\u0590-\u05ff]/)
    return
  }
  if (typeof en === 'function') return
  if (Array.isArray(en)) {
    expect(Array.isArray(he), path).toBe(true)
    expect(en.length, path).toBe((he as unknown[]).length)
    en.forEach((value, index) => compare(value, (he as unknown[])[index], `${path}[${index}]`))
    return
  }
  const a = en as Record<string, unknown>
  const b = he as Record<string, unknown>
  expect(Object.keys(a).sort(), path).toEqual(Object.keys(b).sort())
  Object.keys(a).forEach((key) => compare(a[key], b[key], `${path}.${key}`))
}

test('every Hebrew key has an English value with the same shape', () => {
  compare(english, hebrew, 'strings')
})

test('English parameterized labels keep supplied values and pluralization', () => {
  expect(english.time.minutesAgo(3)).toContain('3')
  expect(english.names.join(['A', 'B'])).toBe('A and B')
  expect(english.chats.messagesCount(1)).toBe('1 message')
  expect(english.chats.messagesCount(2)).toBe('2 messages')
  expect(english.layout.signedInAs('Synthetic', 'test')).toContain('Synthetic')
})
