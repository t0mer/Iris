import { afterEach, expect, test, vi } from 'vitest'

// Non-React modules can be reloaded to simulate a fresh browser page.
afterEach(() => {
  vi.restoreAllMocks()
  localStorage.setItem('iris-language', 'he')
  vi.resetModules()
})

test('a fresh browser uses English and left-to-right layout', async () => {
  localStorage.removeItem('iris-language')
  vi.resetModules()
  const lang = await import('./language')
  expect(lang.language).toBe('en')
  expect(lang.locale).toBe('en-US')
  expect(lang.dir).toBe('ltr')
  lang.applyLanguage()
  expect(document.documentElement.lang).toBe('en')
  expect(document.documentElement.dir).toBe('ltr')
  const { t } = await import('./i18n')
  expect(t('layout.appName')).toBe('Iris')
  expect(t('common.save')).toBe('Save')
  const { he } = await import('./he')
  expect(he('Edit {name}', { name: 'Synthetic' })).toBe('Edit Synthetic')
  const { fileSize } = await import('./format')
  expect(fileSize(2048)).toBe('2 KB')
})

test('a saved Hebrew choice survives a new page load and sets RTL', async () => {
  vi.resetModules()
  const first = await import('./language')
  expect(first.saveLanguage('he')).toBe(true)
  vi.resetModules()
  const next = await import('./language')
  expect(next.language).toBe('he')
  expect(next.dir).toBe('rtl')
  next.applyLanguage()
  expect(document.documentElement.lang).toBe('he')
  expect(document.documentElement.dir).toBe('rtl')
  const { t } = await import('./i18n')
  expect(t('common.save')).toBe('שמירה')
})

test('unknown or inaccessible storage falls back to English', async () => {
  localStorage.setItem('iris-language', 'unsupported')
  vi.resetModules()
  const lang = await import('./language')
  expect(lang.getLanguage()).toBe('en')
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  expect(lang.getLanguage()).toBe('en')
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  expect(lang.saveLanguage('he')).toBe(false)
})

test('English provider errors remain sanitized and readable', async () => {
  localStorage.removeItem('iris-language')
  vi.resetModules()
  const { apiErrorMessage } = await import('./apiErrors')
  expect(apiErrorMessage('Invalid credentials', 401)).toBe('Invalid credentials')
  expect(apiErrorMessage('unknown provider secret details', 503)).not.toContain('secret')
  expect(apiErrorMessage('unknown provider secret details', 503)).toContain('503')
})
