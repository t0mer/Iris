import { applyTheme, getTheme, setTheme, watchSystemTheme } from '../../src/lib/theme'

function mockSystem(dark: boolean) {
  const listeners: (() => void)[] = []
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: dark,
      addEventListener: (_: string, fn: () => void) => listeners.push(fn),
    })),
  )
  return listeners
}
const isDark = () => document.documentElement.classList.contains('dark')

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

test('system theme follows the operating system preference', () => {
  mockSystem(true)
  applyTheme()
  expect(isDark()).toBe(true)
  mockSystem(false)
  applyTheme()
  expect(isDark()).toBe(false)
})

test('an explicit choice overrides the system and is remembered', () => {
  mockSystem(true)
  setTheme('light')
  expect(isDark()).toBe(false)
  expect(getTheme()).toBe('light')
  setTheme('dark')
  expect(isDark()).toBe(true)
  setTheme('system')
  expect(getTheme()).toBe('system')
})

test('a system change is followed only while the theme is "system"', () => {
  const listeners = mockSystem(false)
  watchSystemTheme()
  mockSystem(true)
  listeners.forEach((fn) => fn())
  expect(isDark()).toBe(true)
  setTheme('light')
  listeners.forEach((fn) => fn())
  expect(isDark()).toBe(false)
})

test('works when storage is blocked and matchMedia is missing', () => {
  vi.stubGlobal('localStorage', {
    getItem: () => {
      throw new Error('blocked')
    },
    setItem: () => {
      throw new Error('blocked')
    },
    removeItem: () => {
      throw new Error('blocked')
    },
  })
  vi.stubGlobal('matchMedia', undefined)
  expect(getTheme()).toBe('system')
  expect(() => setTheme('dark')).not.toThrow()
  expect(isDark()).toBe(true)
  vi.unstubAllGlobals()
})
