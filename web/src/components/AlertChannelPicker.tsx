import { ChoiceCards } from './ChoiceCards'
import { t } from '../lib/i18n'
import type { AlertReadiness } from '../lib/types'

export const ALERT_CHANNEL_LABELS: Record<string, string> = {
  openwa: 'WhatsApp via OpenWA',
  greenapi: 'WhatsApp via GreenAPI',
  smtp: 'Email via SMTP',
  telegram: 'Telegram bot',
}
export interface RecipientChannelOptions {
  channels: {
    channel: string
    configured: boolean
    error: string | null
    recipients: AlertReadiness['recipients']
  }[]
}

export function AlertChannelPicker({
  options,
  target,
  value,
  onChange,
  disabled,
  label = 'Alert channel',
}: {
  options?: RecipientChannelOptions
  target?: string
  value: string
  onChange: (channel: string) => void
  disabled?: boolean
  label?: string
}) {
  const available =
    options?.channels?.filter((option) => {
      if (!option.configured) return false
      if (!target || option.channel === 'telegram') return true
      const recipient = option.recipients.find((candidate) => candidate.target === target)
      // A new standalone destination is validated by the server when saved.
      return !recipient || recipient.eligible
    }) ?? []
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <ChoiceCards
        label={t(label)}
        value={value}
        disabled={disabled || !available.length}
        onChange={onChange}
        options={[
          ...(value && !available.some((option) => option.channel === value)
            ? [
                {
                  value,
                  label: `${t(ALERT_CHANNEL_LABELS[value] ?? value)} · ${t('Unavailable')}`,
                  disabled: true,
                },
              ]
            : []),
          ...available.map((option) => ({
            value: option.channel,
            label: t(ALERT_CHANNEL_LABELS[option.channel]),
            displayLabel:
              option.channel === 'smtp'
                ? t('Email · SMTP')
                : option.channel === 'telegram'
                  ? 'Telegram'
                  : `WhatsApp · ${option.channel === 'greenapi' ? 'GreenAPI' : 'OpenWA'}`,
          })),
        ]}
      />
      {!available.length && (
        <span role="alert" className="text-warning">
          {t(
            'No configured channel is available for this parent. Configure a provider and destination first.',
          )}
        </span>
      )}
    </div>
  )
}
