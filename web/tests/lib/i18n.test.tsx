import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Login } from '../../src/pages/Login'
import { LanguageSelect } from '../../src/components/LanguageSelect'
import { renderWithApp } from '../test-utils'
import {
  browserLanguage,
  getLanguage,
  setAccountLanguage,
  setLanguage,
  takeLoginLanguageSelection,
  t,
} from '../../src/lib/i18n'

afterEach(() => {
  act(() => {
    setAccountLanguage(null)
    setLanguage('system')
    takeLoginLanguageSelection()
  })
  vi.restoreAllMocks()
})

test.each([
  [['he-IL'], 'he'],
  [['iw-IL'], 'he'],
  [['en-US'], 'en'],
  [['fr-FR', 'he'], 'en'],
  [[], 'en'],
])('resolves browser language %j to %s', (languages, language) => {
  expect(browserLanguage(languages as string[])).toBe(language)
})

test('switching the login to Hebrew preserves credentials and updates RTL and title', async () => {
  renderWithApp(<Login />, { '/api/auth/options': { two_factor_enabled: false } })
  await userEvent.type(screen.getByLabelText('Username'), 'parent')
  await userEvent.type(screen.getByLabelText('Password'), 'secret-pass')
  await userEvent.selectOptions(screen.getByLabelText('Language'), 'he')
  expect(document.documentElement).toHaveAttribute('lang', 'he')
  expect(document.documentElement).toHaveAttribute('dir', 'rtl')
  expect(document.title).toBe('כניסה · Iris')
  expect(screen.getByLabelText('שם משתמש')).toHaveValue('parent')
  expect(screen.getByLabelText('סיסמה')).toHaveValue('secret-pass')
  expect(screen.getByLabelText('סיסמה')).toHaveAttribute('dir', 'ltr')
  expect(screen.getByRole('button', { name: 'כניסה' })).toBeVisible()
  await userEvent.selectOptions(screen.getByLabelText('שפה'), 'en')
  expect(document.documentElement).toHaveAttribute('dir', 'ltr')
})

test('an authenticated language is saved on the account and remains isolated from the next user', async () => {
  act(() => setAccountLanguage({ id: 7, language: 'en' }))
  const calls = renderWithApp(<LanguageSelect />, { '/api/auth/language': { language: 'he' } })
  await userEvent.selectOptions(screen.getByLabelText('Language'), 'he')
  await waitFor(() => expect(screen.getByLabelText('שפה')).toHaveValue('he'))
  expect(calls).toContainEqual({
    method: 'PATCH',
    url: '/api/auth/language',
    body: { language: 'he' },
  })
  act(() => setAccountLanguage({ id: 8, language: 'en' }))
  expect(getLanguage()).toBe('en')
  expect(screen.getByLabelText('Language')).toHaveValue('en')
})

test('system preference follows changes in browser language and falls back to English', () => {
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['he-IL'])
  renderWithApp(<LanguageSelect />, {})
  fireEvent(window, new Event('languagechange'))
  expect(getLanguage()).toBe('he')
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE'])
  fireEvent(window, new Event('languagechange'))
  expect(document.documentElement).toHaveAttribute('dir', 'ltr')
  expect(t('Sign in')).toBe('Sign in')
})

test('a failed account save keeps the previous language and exposes the error', async () => {
  act(() => setAccountLanguage({ id: 7, language: 'en' }))
  renderWithApp(<LanguageSelect />, {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 503 })),
  )
  await userEvent.selectOptions(screen.getByLabelText('Language'), 'he')
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save language')
  expect(getLanguage()).toBe('en')
})
test('server validation and joined readiness messages are translated without losing destinations', () => {
  setLanguage('he')
  expect(t('alerts.recipient_channels: No WhatsApp number.')).toBe(
    'ערוצי ההתראות של ההורים: לא הוגדר מספר WhatsApp.',
  )
  expect(
    t(
      'No eligible recipients for WhatsApp via GreenAPI. Check destinations and child assignments.',
    ),
  ).toBe('אין נמענים מתאימים עבור WhatsApp via GreenAPI. יש לבדוק את פרטי הנמענים ואת שיוך הילדים.')
})
