import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import type { DatabaseStatus, DbConfigInfo } from '../lib/types'
import { DatabaseTab } from './DatabaseTab'

const sqlite: DbConfigInfo = {
  kind: 'sqlite',
  host: '',
  port: null,
  name: '',
  user: '',
  tls: false,
  password_set: false,
}
const pg: DbConfigInfo = {
  kind: 'postgresql',
  host: 'db.local',
  port: 5432,
  name: 'iris',
  user: 'iris',
  tls: false,
  password_set: true,
}
const idle = { state: 'idle', table: '', copied: {}, error: null } as const
const status = (over: Partial<DatabaseStatus> = {}): DatabaseStatus => ({
  running: sqlite,
  running_source: 'default',
  saved: sqlite,
  restart_required: false,
  env_override: false,
  copy_job: idle,
  ...over,
})
const probeOk = { ok: true, detail: 'Connected.', version: '16.1', empty: true, warning: null }

test('SQLite needs no connection details', async () => {
  renderWithApp(<DatabaseTab />, { '/api/database': status() })
  expect(await screen.findByText('SQLite', { selector: 'span' })).toBeInTheDocument()
  expect(screen.queryByLabelText('שרת')).not.toBeInTheDocument()
  expect(screen.getByLabelText('סוג')).toHaveValue('sqlite')
})

test('choosing a server database shows its fields with the usual port', async () => {
  renderWithApp(<DatabaseTab />, { '/api/database': status() })
  await userEvent.selectOptions(await screen.findByLabelText('סוג'), 'postgresql')
  expect(screen.getByLabelText('שרת')).toBeInTheDocument()
  expect(screen.getByLabelText('פורט')).toHaveValue(5432)
  await userEvent.selectOptions(screen.getByLabelText('סוג'), 'mysql')
  expect(screen.getByLabelText('פורט')).toHaveValue(3306)
  expect(screen.getByText(/utf8mb4/)).toBeInTheDocument()
})

test('a saved password is never shown, only that one is stored', async () => {
  renderWithApp(<DatabaseTab />, { '/api/database': status({ saved: pg }) })
  const pw = await screen.findByLabelText(/^סיסמה/)
  expect(pw).toHaveValue('')
  expect(pw).toHaveAttribute('placeholder', 'שמורה, השאר/י ריק כדי לשמור עליה')
  expect(screen.getByLabelText('שרת')).toHaveValue('db.local')
})

test('test connection sends the typed values and shows the answer and any warning', async () => {
  const calls = renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg }),
    '/api/database/test': { ...probeOk, warning: 'The database uses latin1.' },
  })
  await userEvent.type(await screen.findByLabelText(/^סיסמה/), 'pw1')
  await userEvent.click(screen.getByRole('button', { name: /בדיקת החיבור/ }))
  expect(await screen.findByText('החיבור הצליח.')).toBeInTheDocument()
  expect(screen.getByText(/ערכת התווים latin1/)).toBeInTheDocument()
  const post = calls.find((c) => c.url === '/api/database/test')
  expect(post!.body).toMatchObject({
    kind: 'postgresql',
    host: 'db.local',
    port: 5432,
    password: 'pw1',
  })
})

test('a blank password is sent as null so the stored one is kept', async () => {
  const calls = renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg }),
    '/api/database/test': probeOk,
  })
  await userEvent.click(await screen.findByRole('button', { name: /בדיקת החיבור/ }))
  await screen.findByText('החיבור הצליח.')
  expect(calls.find((c) => c.url === '/api/database/test')!.body).toMatchObject({ password: null })
})

test('a failed test says why', async () => {
  renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg }),
    '/api/database/test': { ok: false, detail: 'The user name or password was refused.' },
  })
  await userEvent.click(await screen.findByRole('button', { name: /בדיקת החיבור/ }))
  expect(await screen.findByText(/הסיסמה נדחו/)).toBeInTheDocument()
})

test('save sends the form and tells the owner to restart', async () => {
  const calls = renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg, restart_required: true }),
  })
  expect(await screen.findByText(/יש להפעיל מחדש את שירות איריס/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.method === 'PUT')
  expect(put!.body).toMatchObject({ kind: 'postgresql', name: 'iris', password: null })
})

test('an environment override locks the form and says so', async () => {
  renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg, running: pg, running_source: 'env', env_override: true }),
  })
  expect(await screen.findByText(/IRIS_DATABASE_URL/)).toBeInTheDocument()
  expect(screen.getByLabelText('שרת')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'שמירה' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: /שימוש ב-SQLite שוב/ })).not.toBeInTheDocument()
})

test('copying asks first, then starts the copy', async () => {
  const calls = renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg, restart_required: true }),
  })
  await userEvent.click(
    await screen.findByRole('button', { name: /העתקת הנתונים שלי אל PostgreSQL/ }),
  )
  const dialog = await screen.findByRole('alertdialog')
  expect(within(dialog).getByText(/לא ייכללו/)).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('button', { name: 'העתקת הנתונים שלי' }))
  expect(calls.some((c) => c.method === 'POST' && c.url === '/api/database/copy')).toBe(true)
})

test('copy progress, result and failure are shown', async () => {
  const running = status({
    saved: pg,
    restart_required: true,
    copy_job: { state: 'running', table: 'messages', copied: {}, error: null },
  })
  const { unmount } = renderOnce(running)
  expect(await screen.findByText(/מעתיקה הודעות/)).toBeInTheDocument()
  unmount()
  const done = status({
    saved: pg,
    restart_required: true,
    copy_job: {
      state: 'done',
      table: '',
      copied: { messages: 120, alerts: 4, jobs: 0 },
      error: null,
    },
  })
  const second = renderOnce(done)
  expect(
    await screen.findByText(/יש להפעיל את איריס מחדש כדי להתחיל להשתמש במסד הנתונים החדש/),
  ).toBeInTheDocument()
  expect(screen.getByText('120')).toBeInTheDocument()
  expect(screen.queryByText(/jobs/)).not.toBeInTheDocument() // empty tables are not listed
  second.unmount()
  const failed = status({
    saved: pg,
    restart_required: true,
    copy_job: {
      state: 'failed',
      table: '',
      copied: {},
      error: 'The new database already contains data.',
    },
  })
  renderOnce(failed)
  expect(await screen.findByRole('alert')).toHaveTextContent('כבר מכיל נתונים')
})

function renderOnce(s: DatabaseStatus) {
  renderWithApp(<DatabaseTab />, { '/api/database': s })
  return { unmount: cleanup }
}

test('going back to SQLite is confirmed and removes the saved choice', async () => {
  const calls = renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg, restart_required: true }),
  })
  await userEvent.click(await screen.findByRole('button', { name: /שימוש ב-SQLite שוב/ }))
  const dialog = await screen.findByRole('alertdialog')
  await userEvent.click(within(dialog).getByRole('button', { name: 'שימוש ב-SQLite' }))
  expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/database')).toBe(true)
})

test('an unreadable saved choice is shown as an error', async () => {
  renderWithApp(<DatabaseTab />, {
    '/api/database': status({ config_error: 'database.json cannot be read (InvalidTag).' }),
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('לא ניתן לקרוא')
})

test('a refused connection is announced as an alert', async () => {
  renderWithApp(<DatabaseTab />, {
    '/api/database': status({ saved: pg }),
    '/api/database/test': { ok: false, detail: 'Could not reach the server.' },
  })
  await userEvent.click(await screen.findByRole('button', { name: /בדיקת החיבור/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('לא ניתן להתחבר')
})

test('the password field explains when the saved password is kept', async () => {
  renderWithApp(<DatabaseTab />, { '/api/database': status({ saved: pg }) })
  expect(await screen.findByText(/שינוי השרת, הפורט או שם מסד הנתונים/)).toBeInTheDocument()
})
