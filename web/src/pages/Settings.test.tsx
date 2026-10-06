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
  'alerts.timezone': 'Asia/Jerusalem',
}

const thresholds = [
  { category: 'violence', low: 0.2, high: 0.7, default_low: 0.2, default_high: 0.7 },
  { category: 'hate', low: 0.2, high: 0.7, default_low: 0.2, default_high: 0.7 },
]

function renderPage() {
  const calls: { url: string; body?: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined })
      const body = url.startsWith('/api/settings/test')
        ? { ok: true, detail: 'OpenAI Moderation answered' }
        : url.startsWith('/api/instances')
          ? []
          : url.startsWith('/api/settings/thresholds')
            ? thresholds
            : settings
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

test('never shows the saved key, and blank secret is not sent on save', async () => {
  const calls = renderPage()
  expect(await screen.findByPlaceholderText(/saved, leave blank/)).toHaveValue('')
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'cloudflare')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'transcription.provider': 'cloudflare' })
})

test('test button reports the result', async () => {
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Test' }))[0])
  expect(await screen.findByText(/OpenAI Moderation answered/)).toBeInTheDocument()
})

test('alert settings are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Alerts' }))
  const cooldown = await screen.findByLabelText(/Cooldown per chat/)
  await userEvent.clear(cooldown)
  await userEvent.type(cooldown, '30')
  await userEvent.click(screen.getByLabelText(/Also alert on items needing review/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'alerts.cooldown_minutes': 30,
    'alerts.alert_on_review': true,
  })
})

test('only changed thresholds are sent, as overrides of the defaults', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Classification' }))
  const high = await screen.findByLabelText('violence high')
  await userEvent.clear(high)
  await userEvent.type(high, '0.9')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'classification.thresholds': { violence: { low: 0.2, high: 0.9 } },
  })
})

test('scope toggles and retention are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Scope' }))
  await userEvent.click(await screen.findByLabelText('Groups'))
  await userEvent.click(screen.getByRole('tab', { name: 'Retention' }))
  const days = await screen.findByLabelText(/Keep messages for/)
  await userEvent.clear(days)
  await userEvent.type(days, '30')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'scope.monitor_groups': false,
    'retention.message_days': 30,
  })
})

test('password change checks the confirmation before calling the API', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Account' }))
  await userEvent.type(screen.getByLabelText('Current password'), 'old-password')
  await userEvent.type(screen.getByLabelText(/^New password/), 'new-password-1')
  await userEvent.type(screen.getByLabelText('Repeat new password'), 'different')
  await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText(/do not match/)).toBeInTheDocument()
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
  expect(await screen.findByRole('alert')).toHaveTextContent(/Could not load the settings/)
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
})

test('an untouched secret field leaves nothing pending and sends nothing', async () => {
  const calls = renderPage()
  await userEvent.type(await screen.findByPlaceholderText(/saved, leave blank/), 'x')
  await userEvent.clear(screen.getByPlaceholderText(/saved, leave blank/)) // back to blank = keep the saved key
  await userEvent.click(await screen.findByRole('button', { name: 'Save' }))
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false) // nothing to send
  expect(screen.queryByText('You have unsaved changes.')).not.toBeInTheDocument()
})

test('an emptied number is refused with a message instead of being saved as zero', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Retention' }))
  const days = await screen.findByLabelText(/Keep messages for/)
  await userEvent.clear(days)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/Enter a number for "Keep messages for"/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false)
})

test('thresholds that are not a valid range are refused before they are sent', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Classification' }))
  const low = await screen.findByLabelText('violence low')
  await userEvent.clear(low)
  await userEvent.type(low, '0.9') // low above high (0.7)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/Thresholds must be numbers from 0 to 1/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false)
})

test('clearing a saved key asks first and sends nothing when cancelled', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('button', { name: 'Clear' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Remove the saved key?' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(calls.some((c) => c.url === '/api/settings' && c.body)).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
  await userEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove key' }),
  )
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'openai.api_key': null })
})
