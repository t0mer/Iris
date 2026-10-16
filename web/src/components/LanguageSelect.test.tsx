import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LanguageSelect } from './LanguageSelect'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.setItem('iris-language', 'he')
  document.documentElement.dir = 'rtl'
})

test('the language picker saves English and reloads once', async () => {
  const reload = vi.fn()
  render(<LanguageSelect reload={reload} />)
  const picker = screen.getByRole('combobox', { name: 'Language / שפה' })
  expect(picker).toHaveValue('he')
  await userEvent.selectOptions(picker, 'en')
  expect(localStorage.getItem('iris-language')).toBe('en')
  expect(document.documentElement.dir).toBe('ltr')
  expect(reload).toHaveBeenCalledTimes(1)
})

test('a storage failure keeps the choice visible and does not reload', async () => {
  const reload = vi.fn()
  render(<LanguageSelect reload={reload} />)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  await userEvent.selectOptions(screen.getByRole('combobox'), 'en')
  expect(screen.getByRole('alert')).toHaveTextContent('Could not save language preference')
  expect(reload).not.toHaveBeenCalled()
  expect(screen.getByRole('combobox')).toHaveValue('he')
})
