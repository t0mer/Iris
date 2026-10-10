import { Link, MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Toaster } from '../../src/components/ui/toaster'
import { Settings } from '../../src/pages/Settings'

const settings = {
  'openwa.webhook_attempts': 3,
  'openwa.recovery_enabled': true,
  'openwa.recovery_hours': 24,
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
      if (url.startsWith('/api/users/security/config'))
        return new Response(JSON.stringify({ smtp: {}, enabled: false, password_set: false }), {
          status: 200,
        })
      if (url.startsWith('/api/users')) return new Response('[]', { status: 200 })
      if (url.startsWith('/api/learning/examples'))
        return new Response(JSON.stringify({ items: [] }), { status: 200 })
      if (url.startsWith('/api/learning/runs'))
        return new Response(
          JSON.stringify({
            items: [],
            summary: {
              sampled_runs: 0,
              reviewed_messages: 0,
              baseline: { false_positive: 0, false_negative: 0, review: 0 },
              candidate: { false_positive: 0, false_negative: 0, review: 0 },
            },
          }),
          { status: 200 },
        )
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
      <MemoryRouter>
        <Link to="/settings?tab=Alerts">Open alert settings</Link>
        <Settings />
      </MemoryRouter>
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
  await userEvent.click(await screen.findByRole('button', { name: 'Test Ollama' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test Ollama image' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test transcription connection' }))
  expect(calls.some((c) => c.url === '/api/settings/test/ollama')).toBe(true)
  expect(calls.some((c) => c.url === '/api/settings/test/ollama_image')).toBe(true)
  expect(calls.some((c) => c.url === '/api/settings/test/local_whisper')).toBe(true)
  expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Provider')).toBeInTheDocument()
})

test('parent channel and recipients share one panel and testing requires saving the channel', async () => {
  renderPage({
    ...settings,
    'alerts.channel': 'smtp',
    'alerts.recipient': 'email:parent@example.com',
  })
  await userEvent.click(await screen.findByRole('tab', { name: 'Notifications' }))
  const panel = screen.getByRole('heading', { name: 'Parent alert delivery' }).closest('section')!
  expect(
    within(panel).getByRole('heading', { name: 'Parent alert recipients' }),
  ).toBeInTheDocument()
  expect(within(panel).getByLabelText('Send parent alerts using')).toHaveValue('smtp')
  expect(within(panel).queryByLabelText('OpenWA sender phone')).not.toBeInTheDocument()
  await userEvent.selectOptions(
    within(panel).getByLabelText('Send parent alerts using'),
    'greenapi',
  )
  expect(within(panel).getByRole('button', { name: 'Test parent alert delivery' })).toBeDisabled()
  expect(within(panel).getByText(/Save changes to apply this channel/)).toBeInTheDocument()
  expect(within(panel).queryByLabelText(/Telegram chat ID for/)).not.toBeInTheDocument()
  await userEvent.selectOptions(
    within(panel).getByLabelText('Send parent alerts using'),
    'telegram',
  )
  expect(within(panel).getByLabelText(/Telegram chat ID for/)).toBeInTheDocument()
})

test('OpenWA retry and catch-up settings save typed values and offer manual recovery', async () => {
  const user = userEvent.setup()
  const calls = renderPage()
  await user.click(await screen.findByRole('tab', { name: 'Notifications' }))
  const attempts = screen.getByLabelText('Webhook delivery attempts (1–5 total)')
  await user.clear(attempts)
  await user.type(attempts, '5')
  expect(screen.getByRole('button', { name: 'Recover missed messages now' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(
    calls.some((c) => c.body && JSON.parse(c.body).settings?.['openwa.webhook_attempts'] === 5),
  ).toBe(true)
  await user.click(screen.getByRole('button', { name: 'Recover missed messages now' }))
  expect(calls.some((c) => c.url === '/api/schedules/openwa_recovery/run')).toBe(true)
})

test('never shows the saved key, and blank secret is not sent on save', async () => {
  const calls = renderPage()
  expect(await screen.findByPlaceholderText(/saved, leave blank/)).toHaveValue('')
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'cloudflare')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
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
  const model = await screen.findByLabelText('Ollama model')
  await userEvent.clear(model)
  await userEvent.type(model, 'new-model')
  await userEvent.click(screen.getByRole('button', { name: 'Test Ollama' }))
  const testCall = calls.find((c) => c.url === '/api/settings/test/ollama')
  expect(JSON.parse(testCall!.body!)).toMatchObject({
    model: 'new-model',
    base_url: 'http://mac.example:11434',
  })
  await userEvent.selectOptions(screen.getByLabelText('Classification provider'), 'openai')
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'cloudflare')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toMatchObject({
    'runtime.ollama_model': 'new-model',
    'runtime.classification_provider': 'openai',
    'runtime.transcription_provider': 'cloudflare',
  })
})

test('test button reports the result', async () => {
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Test' }))[0])
  expect(await screen.findByText(/OpenAI Moderation answered/)).toBeInTheDocument()
})

test.each([false, true])('review buttons save a boolean when initially %s', async (enabled) => {
  const calls = renderPage({ ...settings, 'alerts.review_buttons': enabled })
  await userEvent.click(await screen.findByRole('tab', { name: 'Notifications' }))
  await userEvent.click(screen.getByRole('switch', { name: 'Add review buttons to alerts' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'alerts.review_buttons': !enabled })
})

test('learning defaults to Off and saves Shadow explicitly', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Classification' }))
  const mode = screen.getByLabelText('Ollama learning from reviewed text')
  expect(mode).toHaveValue('off')
  await userEvent.selectOptions(mode, 'shadow')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'classification.learning_mode': 'shadow' })
})

test('semantic retrieval saves its model and numeric cutoff and has a connection test', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Classification' }))
  await userEvent.selectOptions(screen.getByLabelText('Find reviewed examples by'), 'semantic')
  await userEvent.type(screen.getByLabelText('Installed Ollama embedding model'), 'multilingual')
  const cutoff = screen.getByLabelText('Minimum semantic similarity (0 to 1)')
  await userEvent.clear(cutoff)
  await userEvent.type(cutoff, '0.8')
  await userEvent.click(screen.getByRole('button', { name: 'Test embedding model' }))
  expect(calls.some((c) => c.url === '/api/settings/test/ollama_embedding')).toBe(true)
  const embeddingTest = calls.find((c) => c.url === '/api/settings/test/ollama_embedding')
  expect(JSON.parse(embeddingTest!.body!).model).toBe('multilingual')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'classification.learning_retrieval': 'semantic',
    'classification.learning_embedding_model': 'multilingual',
    'classification.learning_min_similarity': 0.8,
  })
})

test('Retention shows separate provider archive status and saves bounded recovery controls', async () => {
  const calls = renderPage({
    ...settings,
    'media.recovery_attempts': 1,
    'media.recovery_wait_seconds': 5,
    provider_media: {
      archive_enabled: true,
      archive_outbound: true,
      archive_ttl_days: 0,
      download_timeout_seconds: 60,
      managed_by: 'OpenWA deployment',
    },
  })
  await userEvent.click(await screen.findByRole('tab', { name: 'Retention' }))
  expect(screen.getByText(/OpenWA archive: Enabled/)).toBeInTheDocument()
  expect(screen.getByText(/No automatic expiry/)).toBeInTheDocument()
  expect(screen.getByRole('switch', { name: 'Keep checked media in Iris' })).not.toBeChecked()
  const attempts = screen.getByLabelText('Media recovery attempts (0 disables)')
  await userEvent.clear(attempts)
  await userEvent.type(attempts, '2')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'media.recovery_attempts': 2 })
})

test('alert settings are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Notifications' }))
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
  await userEvent.click(await screen.findByRole('tab', { name: 'Users' }))
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
      <MemoryRouter>
        <Link to="/settings?tab=Alerts">Open alert settings</Link>
        <Settings />
      </MemoryRouter>
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

test('the follow-up setting is on by default and can be switched off', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Notifications' }))
  await userEvent.click(await screen.findByLabelText(/Tell me when an alerted message is edited/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'alerts.notify_changes': false })
})

// --- media ---

async function openMediaTab() {
  await userEvent.click(await screen.findByRole('tab', { name: 'Media' }))
}

test('media is off by default and the options appear only when it is turned on', async () => {
  renderPage()
  await openMediaTab()
  expect(screen.getByRole('switch', { name: 'Keep media' })).not.toBeChecked()
  expect(screen.queryByText('What to keep')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('switch', { name: 'Keep media' }))
  expect(await screen.findByText('What to keep')).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: /Only what Iris judges harmful/ })).toBeChecked()
  expect(screen.getByText(/never kept, whatever you choose/)).toBeInTheDocument()
})

test('choosing what to keep and saving sends the policy', async () => {
  const calls = renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'Keep media' }))
  await userEvent.click(await screen.findByRole('radio', { name: /Everything/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'media.policy': 'all' })
})

test('the S3 fields show only for S3, and the secret is never shown', async () => {
  renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'Keep media' }))
  expect(screen.queryByLabelText('Endpoint')).not.toBeInTheDocument()
  expect(screen.getByText(/media<\/code> folder|media folder|data folder/)).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Storage'), 's3')
  expect(screen.getByLabelText(/^Endpoint/)).toBeInTheDocument()
  expect(screen.getByLabelText('Bucket')).toBeInTheDocument()
  expect(screen.getByLabelText(/^Region/)).toHaveValue('auto')
  expect(screen.getByPlaceholderText('Not set')).toHaveValue('')
})

test('test storage sends the typed values nested under media', async () => {
  const calls = renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'Keep media' }))
  await userEvent.selectOptions(screen.getByLabelText('Storage'), 's3')
  await userEvent.type(screen.getByLabelText(/^Endpoint/), 'http://seaweed.lan:8333')
  await userEvent.type(screen.getByLabelText('Bucket'), 'iris-media')
  await userEvent.type(screen.getByLabelText('Access key ID'), 'key1')
  await userEvent.type(screen.getByPlaceholderText('Not set'), 'secret1')
  await userEvent.click(screen.getByRole('button', { name: 'Test storage' }))
  expect(await screen.findByText('OpenAI Moderation answered')).toBeInTheDocument()
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
  await userEvent.click(screen.getByRole('switch', { name: 'Keep media' }))
  await userEvent.click(screen.getByRole('tab', { name: 'Retention' }))
  const days = await screen.findByLabelText('Keep media for (days)')
  await userEvent.clear(days)
  await userEvent.type(days, '45')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'media.policy': 'harmful',
    'media.retention_days': 45,
  })
})

test('files kept earlier can be deleted, even when keeping is off', async () => {
  const calls = renderPage()
  await openMediaTab()
  expect(screen.getByRole('switch', { name: 'Keep media' })).not.toBeChecked()
  expect(await screen.findByText('Kept now')).toBeInTheDocument()
  expect(
    screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === '3 files, 3.0 MB'),
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Delete all kept media/ }))
  await userEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete media' }),
  )
  expect(calls.some((c) => c.url === '/api/media')).toBe(true)
})

test('says plainly that videos are not kept', async () => {
  renderPage()
  await openMediaTab()
  await userEvent.click(screen.getByRole('switch', { name: 'Keep media' }))
  expect(await screen.findByText(/Videos are not kept at all/)).toBeInTheDocument()
})

test('the Users tab has a switch that remembers "show content by default" on this browser', async () => {
  renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Users' }))
  const sw = await screen.findByRole('switch', { name: 'Show content by default' })
  expect(sw).not.toBeChecked()
  await userEvent.click(sw)
  expect(sw).toBeChecked()
  expect(localStorage.getItem('iris-show-content')).toBe('1')
  await userEvent.click(sw)
  expect(localStorage.getItem('iris-show-content')).toBeNull()
})

test('Users combines roles, 2FA and account settings; Notifications contains SMTP', async () => {
  renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Users' }))
  expect(await screen.findByRole('heading', { name: 'Users and roles' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Two-factor authentication' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Change password' })).toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Tools' })).not.toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Account' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'SMTP server' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('tab', { name: 'Notifications' }))
  expect(await screen.findByRole('heading', { name: 'SMTP server' })).toBeInTheDocument()
  expect(
    screen.queryByRole('heading', { name: 'Two-factor authentication' }),
  ).not.toBeInTheDocument()
})

test('an in-app link changes the tab while Settings remains mounted', async () => {
  renderPage()
  await screen.findByRole('tab', { name: 'Providers' })
  await userEvent.click(screen.getByRole('link', { name: 'Open alert settings' }))
  expect(screen.getByRole('tab', { name: 'Notifications' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
})
