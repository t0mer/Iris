import { apiErrorMessage } from './apiErrors'

test('explains server validation without exposing provider details', () => {
  expect(apiErrorMessage('Password must be at least 8 characters', 422)).toBe(
    'הסיסמה צריכה להכיל לפחות 8 תווים',
  )
  expect(
    apiErrorMessage({ 'retention.message_days': 'must be an integer between 1 and 3650' }, 422),
  ).toContain('בין 1 ל־3650')
  expect(apiErrorMessage([{ msg: 'Field required' }], 422)).toBe('שדה חובה')
  expect(apiErrorMessage('unknown provider detail', 503)).toContain('503')
  expect(apiErrorMessage('unknown provider detail', 503)).not.toContain('provider')
})

test('translates successful checks separately from validation failures', () => {
  expect(apiErrorMessage('Connected.', 200)).toBe('החיבור הצליח.')
  expect(apiErrorMessage('The user name or password was refused.', 400)).toBe(
    'שם המשתמש או הסיסמה נדחו.',
  )
})
