import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import { ChoiceCards } from './ChoiceCards'
import { ALERT_CHANNEL_LABELS, type RecipientChannelOptions } from './AlertChannelPicker'

type Health = {
  provider: string
  name: string
  status: string
  error: string | null
  delivery_error?: string | null
}

export function ProviderHealth() {
  const health = useQuery({
    queryKey: ['provider-health'],
    queryFn: () => api<Health[]>('/api/settings/provider-health'),
    refetchInterval: 30_000,
  })
  if (health.isError) return <p role="alert">{t('Could not load provider status.')}</p>
  if (!health.data?.length)
    return (
      <p className="text-sm text-muted-foreground">
        {t(
          'Provider checks have not run yet. Run Provider health checks in Schedules to check now.',
        )}
      </p>
    )
  return (
    <ul className="flex flex-col gap-2">
      {health.data.map((provider) => (
        <li
          key={provider.provider}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"
        >
          <span className="font-medium">{provider.name}</span>
          <span className={provider.status === 'up' ? 'text-success' : 'text-danger'}>
            {t(provider.status === 'up' ? 'Available' : 'Unavailable')}
          </span>
          {provider.error && (
            <span dir="auto" className="text-xs text-muted-foreground">
              {t(provider.error)}
            </span>
          )}
          {provider.delivery_error && (
            <span className="w-full text-xs text-warning">
              {t(
                provider.delivery_error === 'DeferredError'
                  ? 'System notification delivery was deferred by the sending rate limit.'
                  : provider.delivery_error,
              )}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

export function ProviderAlertChannel({
  value,
  onChange,
}: {
  value: string
  onChange: (channel: string) => void
}) {
  const channels = useQuery({
    queryKey: ['recipient-channels'],
    queryFn: () => api<RecipientChannelOptions>('/api/settings/recipient-channels'),
  })
  return (
    <ChoiceCards
      label={t('System notification channel')}
      value={value}
      onChange={onChange}
      options={[
        ...(channels.data?.channels
          ?.filter((channel) => channel.configured)
          .map((channel) => ({
            value: channel.channel,
            label: t(ALERT_CHANNEL_LABELS[channel.channel]),
          })) ?? []),
      ]}
    />
  )
}
