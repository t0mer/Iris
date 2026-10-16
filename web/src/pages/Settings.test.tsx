import { he } from '../lib/he'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Toaster } from '../components/ui/toaster'
import { Settings } from './Settings'

const settings = {
  'openai.api_key': { set: true },
  'transcription.provider': 'openai',
  'transcription.openai_model': 'gpt-4o-mini-transcribe',
  'transcription.cloudflare_account_id': null,
  'transcription.cloudflare_api_token': { set: false },
  'transcription.cloudflare_model': '@cf/openai/whisper-large-v3-turbo',
  'classification.model': 'omni-moderation-latest',
  'classification.context_window_size': 8,
  'classification.context_max_age_hours': 6,
  'scope.monitor_from_me': true,
  'scope.monitor_direct': true,
  'scope.monitor_groups': true,
  'retention.message_days': 90,
  'retention.alert_days': 365,
  'alerts.sender_instance_id': null,
  'alerts.recipient': null,
  'alerts.cooldown_minutes': 10,
  'alerts.alert_on_review': false,
  'alerts.notify_changes': true,
  'alerts.timezone': 'Asia/Jerusalem',
  'media.policy': 'off',
  'media.backend': 'local',
  'media.s3_endpoint': null,
  'media.s3_bucket': null,
  'media.s3_region': 'auto',
  'media.s3_access_key': null,
  'media.s3_secret_key': { set: false },
  'media.s3_prefix': 'iris/',
  'media.s3_path_style': true,
  'media.retention_days': 30,
}

const thresholds = [
  { category: 'violence', low: 0.2, high: 0.7, default_low: 0.2, default_high: 0.7 },
  { category: 'hate', low: 0.2, high: 0.7, default_low: 0.2, default_high: 0.7 },
]

function renderPage(values: Record<string, unknown> = settings) {
  const calls: { url: string; body?: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined })
      const body = url.startsWith('/api/stats')
        ? { media_files: 3, media_bytes: 3 * 1024 * 1024 }
        : url.startsWith('/api/settings/test')
          ? { ok: true, detail: 'OpenAI Moderation answered' }
          : url.startsWith('/api/instances')
            ? []
            : url.startsWith('/api/settings/thresholds')
              ? thresholds
              : values
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Settings />
      <Toaster />
    </QueryClientProvider>,
  )
  return calls
}

test('local providers show dedicated tests and keep cloud controls hidden', async () => {
  const calls = renderPage({
    ...settings,
    local_providers: {
      classification: 'ollama',
      ollama_model: 'example-model',
      transcription: 'local_whisper',
      transcription_model: 'auto',
      api_key_set: true,
    },
  })
  await userEvent.click(await screen.findByRole('button', { name: he('Test Ollama') }))
  await userEvent.click(screen.getByRole('button', { name: he('Test transcription connection') }))
  expect(calls.some((c) => c.url === '/api/settings/test/ollama')).toBe(true)
  expect(calls.some((c) => c.url === '/api/settings/test/local_whisper')).toBe(true)
  expect(screen.queryByLabelText(he('API key'))).not.toBeInTheDocument()
  expect(screen.getByLabelText(he('Provider'))).toBeInTheDocument()
})

test('never shows the saved key, and blank secret is not sent on save', async () => {
  const calls = renderPage()
  expect(await screen.findByPlaceholderText(/ריק/)).toHaveValue('')
  await userEvent.selectOptions(screen.getByLabelText('ספק'), 'cloudflare')
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'transcription.provider': 'cloudflare' })
})

test('saves edited local model and allows an explicit cloud provider switch', async () => {
  const calls = renderPage({
    ...settings,
    'runtime.classification_provider': 'ollama',
    'runtime.ollama_base_url': 'http://mac.example:11434',
    'runtime.ollama_model': 'old-model',
    'runtime.transcription_provider': 'local_whisper',
    'runtime.whisper_url': 'http://mac.example:8081/v1/audio/transcriptions',
    'runtime.whisper_model': 'auto',
    'runtime.whisper_api_key': { set: true },
  })
  const model = await screen.findByLabelText(he('Ollama model'))
  await userEvent.clear(model)
  await userEvent.type(model, 'new-model')
  await userEvent.click(screen.getByRole('button', { name: he('Test Ollama') }))
  const testCall = calls.find((c) => c.url === '/api/settings/test/ollama')
  expect(JSON.parse(testCall!.body!)).toMatchObject({
    model: 'new-model',
    base_url: 'http://mac.example:11434',
  })
  await userEvent.selectOptions(screen.getByLabelText(he('Classification provider')), 'openai')
  await userEvent.selectOptions(screen.getByLabelText(he('Provider')), 'cloudflare')
  await userEvent.click(screen.getByRole('button', { name: he('Save') }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toMatchObject({
    'runtime.ollama_model': 'new-model',
    'runtime.classification_provider': 'openai',
    'runtime.transcription_provider': 'cloudflare',
  })
})

test('test button reports the result', async () => {
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'בדיקה' }))[0])
  expect(await screen.findByText(/החיבור לסיווג התוכן של OpenAI הצליח/)).toBeInTheDocument()
})

test('alert settings are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'התראות' }))
  const cooldown = await screen.findByLabelText(/תקופת צינון לכל צ׳אט/)
  await userEvent.clear(cooldown)
  await userEvent.type(cooldown, '30')
  await userEvent.click(screen.getByLabelText(/התרעה גם על פריטים שדורשים בדיקה/))
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'alerts.cooldown_minutes': 30,
    'alerts.alert_on_review': true,
  })
})

test('only changed thresholds are sent, as overrides of the defaults', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'סיווג' }))
  const high = await screen.findByLabelText('אלימות מזיק')
  await userEvent.clear(high)
  await userEvent.type(high, '0.9')
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'classification.thresholds': { violence: { low: 0.2, high: 0.9 } },
  })
})

test('scope toggles and retention are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'היקף הניטור' }))
  await userEvent.click(await screen.findByLabelText('קבוצות'))
  await userEvent.click(screen.getByRole('tab', { name: 'שמירה' }))
  const days = await screen.findByLabelText(/שמירת הודעות למשך/)
  await userEvent.clear(days)
  await userEvent.type(days, '30')
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'scope.monitor_groups': false,
    'retention.message_days': 30,
  })
})

test('password change checks the confirmation before calling the API', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'חשבון' }))
  await userEvent.type(screen.getByLabelText('סיסמה נוכחית'), 'old-password')
  await userEvent.type(screen.getByLabelText(/^סיסמה חדשה/), 'new-password-1')
  await userEvent.type(screen.getByLabelText('חזרה על הסיסמה החדשה'), 'different')
  await userEvent.click(screen.getByRole('button', { name: 'שינוי סיסמה' }))
  expect(await screen.findByText(/אינן תואמות/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/auth/password')).toBe(false)
})

// --- regression tests for the review findings -------------------------------------------------

test('a failed settings request shows what failed and offers to try again', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 500 })),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <Settings />
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent(/לא ניתן היה לטעון ההגדרות/)
  expect(screen.getByRole('button', { name: 'ניסיון נוסף' })).toBeInTheDocument()
})

test('an untouched secret field leaves nothing pending and sends nothing', async () => {
  const calls = renderPage()
  await userEvent.type(await screen.findByPlaceholderText(/ריק/), 'x')
  await userEvent.clear(screen.getByPlaceholderText(/ריק/)) // back to blank = keep the saved key
  await userEvent.click(await screen.findByRole('button', { name: 'שמירה' }))
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false) // nothing to send
  expect(screen.queryByText('יש לך שינויים שלא נשמרו.')).not.toBeInTheDocument()
})

test('an emptied number is refused with a message instead of being saved as zero', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'שמירה' }))
  const days = await screen.findByLabelText(/שמירת הודעות למשך/)
  await userEvent.clear(days)
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  expect(await screen.findByText(/יש להזין מספר עבור "שמירת הודעות למשך"/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false)
})

test('thresholds that are not a valid range are refused before they are sent', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'סיווג' }))
  const low = await screen.findByLabelText('אלימות כדאי לבדוק')
  await userEvent.clear(low)
  await userEvent.type(low, '0.9') // low above high (0.7)
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  expect(await screen.findByText(/הספים חייבים להיות מספרים בין 0 ל-1/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false)
})

test('clearing a saved key asks first and sends nothing when cancelled', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('button', { name: 'ניקוי' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'להסיר את המפתח השמור?' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'ביטול' }))
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'ניקוי' }))
  await userEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'הסרת המפתח' }),
  )
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'openai.api_key': null })
})

test('the follow-up setting is on by default and can be switched off', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'התראות' }))
  await userEvent.click(await screen.findByLabelText(/הודעה לי כשהודעה שהתריעו עליה נערכת/))
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'alerts.notify_changes': false })
})

// --- media ---

async function openMediaTab() {
  await userEvent.click(await screen.findByRole('tab', { name: 'מדיה' }))
}

test('media is off by default and the options appear only when it is turned on', async () => {
  renderPage()
  await openMediaTab()
  expect(screen.getByRole('switch', { name: 'שמירת מדיה' })).not.toBeChecked()
  expect(screen.queryByText('מה לשמור')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('switch', { name: 'שמירת מדיה' }))
  expect(await screen.findByText('מה לשמור')).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: /רק מה שאיריס שופטת כמזיק/ })).toBeChecked()
  expect(screen.getByText(/אינו נשמר כמדיה/)).toBeInTheDocument()
})

test('choosing what to keep and saving sends the policy', async () => {
  const calls = renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'שמירת מדיה' }))
  await userEvent.click(await screen.findByRole('radio', { name: /הכול/ }))
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'media.policy': 'all' })
})

test('the S3 fields show only for S3, and the secret is never shown', async () => {
  renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'שמירת מדיה' }))
  expect(screen.queryByLabelText(/Endpoint/)).not.toBeInTheDocument()
  expect(screen.getByText(/תיקיית הנתונים|תיקיית media/)).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('אחסון'), 's3')
  expect(screen.getByLabelText(/Endpoint/)).toBeInTheDocument()
  expect(screen.getByLabelText(/^שם ה-Bucket/)).toBeInTheDocument()
  expect(screen.getByLabelText(/Region/)).toHaveValue('auto')
  expect(screen.getByPlaceholderText('לא מוגדר')).toHaveValue('')
})

test('test storage sends the typed values nested under media', async () => {
  const calls = renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'שמירת מדיה' }))
  await userEvent.selectOptions(screen.getByLabelText('אחסון'), 's3')
  await userEvent.type(screen.getByLabelText(/Endpoint/), 'http://seaweed.lan:8333')
  await userEvent.type(screen.getByLabelText(/^שם ה-Bucket/), 'iris-media')
  await userEvent.type(screen.getByLabelText(/Access Key ID/), 'key1')
  await userEvent.type(screen.getByPlaceholderText('לא מוגדר'), 'secret1')
  await userEvent.click(screen.getByRole('button', { name: 'בדיקת האחסון' }))
  expect(await screen.findByText('החיבור לסיווג התוכן של OpenAI הצליח')).toBeInTheDocument()
  const post = calls.find((c) => c.url === '/api/settings/test/media')
  expect(JSON.parse(post!.body!).media).toMatchObject({
    backend: 's3',
    endpoint: 'http://seaweed.lan:8333',
    bucket: 'iris-media',
    access_key: 'key1',
    secret_key: 'secret1',
    path_style: true,
  })
})

test('media retention is a number and goes to the server as one', async () => {
  const calls = renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'שמירת מדיה' }))
  const days = await screen.findByLabelText('שמירת מדיה למשך (ימים)')
  await userEvent.clear(days)
  await userEvent.type(days, '45')
  await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'media.policy': 'harmful',
    'media.retention_days': 45,
  })
})

test('files kept earlier can be deleted, even when keeping is off', async () => {
  const calls = renderPage()
  await openMediaTab()
  expect(screen.getByRole('switch', { name: 'שמירת מדיה' })).not.toBeChecked()
  expect(await screen.findByText('שמור כעת')).toBeInTheDocument()
  expect(
    screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '3 קבצים, 3.0 מ״ב'),
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /מחיקת כל המדיה השמורה/ }))
  await userEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'מחיקת המדיה' }),
  )
  expect(calls.some((c) => c.url === '/api/media')).toBe(true)
})

test('says plainly that videos are not kept', async () => {
  renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'שמירת מדיה' }))
  expect(await screen.findByText(/סרטונים אינם נשמרים/)).toBeInTheDocument()
})

test('the account tab has a switch that remembers "show content by default" on this browser', async () => {
  renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'חשבון' }))
  const sw = await screen.findByRole('switch', { name: 'הצגת תוכן כברירת מחדל' })
  expect(sw).not.toBeChecked()
  await userEvent.click(sw)
  expect(sw).toBeChecked()
  expect(localStorage.getItem('iris-show-content')).toBe('1')
  await userEvent.click(sw)
  expect(localStorage.getItem('iris-show-content')).toBeNull()
})
