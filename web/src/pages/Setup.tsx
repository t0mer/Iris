import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Circle, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import { Button } from '../components/ui/button'
import { PageHeader } from '../components/PageHeader'
import { PageLoading } from '../components/PageLoading'
import { QueryError } from '../components/QueryError'
import { SetupCheck } from '../components/SetupCheck'

export type SetupStatus = {
  needs_setup: boolean
  steps: { id: string; title: string; ready: boolean; warning: string }[]
  warnings: string[]
  skipped: string[]
  finished: boolean
  active_channel: string
  providers: Record<string, boolean>
  defaults?: Record<string, string | number | boolean | null>
  ai_providers?: {
    id: string
    title: string
    configured: boolean
    required: boolean
    tested: boolean
    detail?: string | null
  }[]
}

const links: Record<string, { label: string; to: string }[]> = {
  openwa: [{ label: 'Configure OpenWA and connect a phone', to: '/instances' }],
  notifiers: [
    { label: 'Configure notification providers', to: '/settings?tab=Notifications' },
    { label: 'Set your test email or personal number', to: '/settings?tab=Users' },
  ],
  parents: [
    { label: 'Add a parent user and configure their destination', to: '/settings?tab=Users' },
    {
      label: 'Select parent alert recipients',
      to: '/settings?tab=Notifications#parent-alert-recipients',
    },
  ],
  children: [{ label: 'Add and connect a child phone', to: '/instances' }],
  ai: [{ label: 'Configure AI providers and models', to: '/settings?tab=Providers' }],
  defaults: [
    { label: 'AI providers', to: '/settings?tab=Providers' },
    { label: 'Monitoring scope', to: '/settings?tab=Scope' },
    { label: 'Media storage', to: '/settings?tab=Media' },
    { label: 'Retention', to: '/settings?tab=Retention' },
    { label: 'Notification timing', to: '/settings?tab=Notifications' },
    { label: 'Public URL and webhook recovery', to: '/settings?tab=Notifications' },
    { label: 'Admin security and sign-in codes', to: '/settings?tab=Users' },
  ],
}

export function Setup() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [selected, setSelected] = useState(0)
  const [result, setResult] = useState('')
  const status = useQuery({
    queryKey: ['setup'],
    queryFn: () => api<SetupStatus>('/api/setup'),
    refetchInterval: 10_000,
  })
  const action = useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: object }) => {
      const value = await api<{ ok?: boolean; detail?: string }>(path, {
        method: 'POST',
        body: JSON.stringify(body ?? {}),
      })
      if (value.ok === false) throw new Error(value.detail || 'Check failed')
      if (value.detail) setResult(value.detail)
      return value
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['setup'] }),
  })
  if (!status.data)
    return status.isError ? (
      <QueryError what="setup status" onRetry={() => void status.refetch()} />
    ) : (
      <PageLoading />
    )
  const data = status.data
  const step = data.steps[selected]
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader
        title="Set up Iris"
        description="Connect monitoring, test notifications and choose who receives alerts. You can skip any step and return here later."
      />
      <nav aria-label="Setup steps" className="grid gap-2 sm:grid-cols-3">
        {data.steps.map((item, index) => (
          <button
            key={item.id}
            type="button"
            aria-current={selected === index ? 'step' : undefined}
            onClick={() => setSelected(index)}
            className={`flex items-center gap-2 rounded-xl border p-3 text-start text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600 dark:focus-visible:outline-purple-300 ${selected === index ? 'border-purple-500 bg-purple-50 text-purple-950 dark:border-purple-400 dark:bg-purple-900/50 dark:text-purple-100' : 'bg-surface'}`}
          >
            {item.ready ? (
              <CheckCircle2 aria-label="Ready" className="size-5 shrink-0 text-success" />
            ) : (
              <Circle aria-hidden="true" className="size-5 shrink-0" />
            )}
            <span>
              {index + 1}. {item.title}
              {data.skipped.includes(item.id) && !item.ready && (
                <span className="block text-xs text-warning">Skipped · still incomplete</span>
              )}
            </span>
          </button>
        ))}
      </nav>
      <section
        className="flex flex-col gap-4 rounded-2xl border bg-surface p-6"
        aria-labelledby="setup-step"
      >
        <h2 id="setup-step" className="text-xl font-semibold">
          {step.title}
        </h2>
        <p className={step.ready ? 'text-success' : 'text-warning'}>
          {step.ready ? 'This step is ready.' : step.warning}
        </p>
        {step.id === 'openwa' && (
          <p>
            Use your Docker/initial configuration, or enter the OpenWA address, API key and session
            manually in Phones. Pair WhatsApp if needed, then check the connection here. Checks do
            not send read receipts.
          </p>
        )}
        {step.id === 'notifiers' && (
          <>
            <p>
              You can configure GreenAPI, SMTP, OpenWA and Telegram. Select an active alert channel
              in Notifications and successfully test at least one provider. Extra providers remain
              available to configure and test.
            </p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.providers).map(([name, ready]) => (
                <span key={name} className="rounded-full border px-3 py-1 text-sm">
                  {name}: {ready ? 'Test passed' : 'Test needed'}
                </span>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              Tests send a real notification. A queued notification counts only after its delivery
              job succeeds. SMTP/GreenAPI tests need your saved admin contact.
            </p>
          </>
        )}
        {step.id === 'ai' && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Save endpoints, credentials and models in Providers, then test each saved connection
              here. Required providers follow your selected classification and transcription routes.
              Tests use built-in samples; cloud tests may incur a small charge. Local Whisper checks
              authentication and available models; use Try it with audio to check real
              transcription.
            </p>
            {data.ai_providers?.map((provider) => (
              <div
                key={provider.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
              >
                <div>
                  <p className="font-medium">
                    {provider.title} · {provider.required ? 'Required' : 'Optional'}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {provider.tested
                      ? 'Test passed for saved settings'
                      : provider.configured
                        ? 'Configured · needs a test'
                        : 'Not configured'}
                  </p>
                </div>
                <SetupCheck
                  key={`${provider.id}:${provider.tested}`}
                  path={`/api/setup/ai/test/${provider.id}`}
                  label={`Test ${provider.title}`}
                  passed={provider.tested}
                  disabled={!provider.configured}
                  detail={provider.detail}
                />
              </div>
            ))}
            <Link className="text-primary underline" to="/try">
              Try a real text, image or recording
            </Link>
          </div>
        )}
        {step.id === 'parents' && (
          <p>
            Add a parent or admin user and select their destination under Parent alert recipients
            for the active channel. GreenAPI and Telegram do not require individual contact
            approval. OpenWA and email require an approved recipient contact.
          </p>
        )}
        {step.id === 'children' && (
          <p>
            Add at least one child phone, pair it with WhatsApp through OpenWA and check that its
            session is ready. Sender phones do not count as monitored children.
          </p>
        )}
        {step.id === 'defaults' && (
          <div className="space-y-3">
            <p>
              Review monitoring scope, data retention, media storage, alert timing and the public
              URL before monitoring real messages. Confirm child assignments and run a sample
              message, image and recording through Try it. Keep a database backup and recovery
              procedure.
            </p>
            {data.defaults && (
              <dl className="grid gap-3 sm:grid-cols-2">
                {Object.entries(data.defaults).map(([name, value]) => (
                  <div key={name} className="rounded-lg border p-3">
                    <dt className="text-sm text-muted-foreground">
                      {(
                        {
                          public_url: 'Public URL',
                          monitor_direct: 'Monitor direct chats',
                          monitor_groups: 'Monitor groups',
                          monitor_from_me: 'Monitor outgoing messages',
                          media_policy: 'Keep media',
                          message_days: 'Message retention (days)',
                          alert_days: 'Alert retention (days)',
                          timezone: 'Alert timezone',
                          recovery_enabled: 'Recover missed OpenWA messages',
                        } as Record<string, string>
                      )[name] ?? name}
                    </dt>
                    <dd className="mt-1 break-words font-medium">
                      {typeof value === 'boolean'
                        ? value
                          ? 'On'
                          : 'Off'
                        : (value ?? 'Not configured')}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-3">
          {links[step.id]?.map((link) => (
            <Link
              key={link.label}
              to={link.to}
              className="rounded-lg border px-4 py-3 text-sm text-primary hover:bg-primary-soft"
            >
              {link.label}
            </Link>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {(step.id === 'openwa' || step.id === 'children') && (
            <SetupCheck
              key={`${step.id}:${step.ready}`}
              path="/api/setup/check"
              label="Check connections"
              passed={step.ready}
              step={step.id}
            />
          )}
          {step.id === 'notifiers' && (
            <>
              <SetupCheck
                key={`smtp:${data.providers.smtp}`}
                path="/api/users/security/smtp/test"
                label="Test saved SMTP"
                passed={data.providers.smtp}
              />
              <SetupCheck
                key={`greenapi:${data.providers.greenapi}`}
                path="/api/users/security/whatsapp/test"
                label="Test saved GreenAPI"
                passed={data.providers.greenapi}
              />
              <SetupCheck
                key={`${data.active_channel}:${data.providers[data.active_channel]}`}
                path="/api/settings/test/alert"
                label={`Test active alert channel (${data.active_channel})`}
                passed={data.providers[data.active_channel]}
              />
            </>
          )}
          {step.id === 'defaults' && (
            <SetupCheck
              key={`defaults:${step.ready}`}
              path="/api/setup/progress"
              label="I reviewed these defaults"
              body={{ review_defaults: true }}
              passed={step.ready}
              step="defaults"
            />
          )}
          <Button disabled={action.isPending} onClick={() => void status.refetch()}>
            Refresh status
          </Button>
          {!step.ready && (
            <Button
              disabled={action.isPending}
              onClick={async () => {
                await action
                  .mutateAsync({ path: '/api/setup/progress', body: { skip: step.id } })
                  .then(() => setSelected(Math.min(selected + 1, data.steps.length - 1)))
                  .catch(() => {})
              }}
            >
              Skip this step
            </Button>
          )}
          {selected < data.steps.length - 1 && (
            <Button onClick={() => setSelected(selected + 1)}>Next</Button>
          )}
        </div>
        {result && (
          <p role="status" className="text-sm">
            {result}
          </p>
        )}
        {action.isError && (
          <p role="alert" className="text-sm text-danger">
            {action.error.message}
          </p>
        )}
      </section>
      {data.warnings.length > 0 && (
        <section
          className="rounded-xl border bg-warning-soft p-5"
          aria-label="Incomplete setup warnings"
        >
          <h2 className="font-semibold">Iris may not work correctly yet</h2>
          <ul className="mt-2 list-disc space-y-1 ps-5 text-sm">
            {data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>
      )}
      <Button
        disabled={action.isPending}
        onClick={async () => {
          await action
            .mutateAsync({
              path: '/api/setup/progress',
              body: { finish: true, acknowledge_incomplete: data.warnings.length > 0 },
            })
            .then(() => navigate('/'))
            .catch(() => {})
        }}
      >
        <ShieldCheck className="size-4" />{' '}
        {data.warnings.length ? 'Continue to Home with these warnings' : 'Finish setup'}
      </Button>
    </div>
  )
}
