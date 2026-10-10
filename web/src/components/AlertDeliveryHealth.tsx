import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { AlertReadiness } from '../lib/types'

export function AlertDeliveryHealth({ channel }: { channel?: string }) {
  const { data, isError, refetch } = useQuery({
    queryKey: ['alert-readiness', channel],
    queryFn: () =>
      api<AlertReadiness>(`/api/settings/alert-readiness${channel ? `?channel=${channel}` : ''}`),
    refetchInterval: 30_000,
  })
  if (isError)
    return (
      <p role="alert">
        Could not check alert delivery.{' '}
        <button className="underline" onClick={() => void refetch()}>
          Retry
        </button>
      </p>
    )
  if (!data?.recipients) return null
  return (
    <section
      className="flex flex-col gap-3 rounded-md border p-3"
      aria-label="Alert delivery readiness"
    >
      <p
        className={data.ready ? 'text-sm text-success' : 'text-sm text-danger'}
        role={data.ready ? 'status' : 'alert'}
      >
        {data.ready ? `${data.eligible_count} eligible recipient(s) for this channel.` : data.error}
      </p>
      <p className="text-sm text-muted-foreground">
        {data.channel === 'greenapi'
          ? 'GreenAPI requires a verified connection and a recipient number or group ID. Individual sender and recipient approval is not required.'
          : data.channel === 'telegram'
            ? 'Telegram requires a bot token and a destination chat ID. Individual sender and recipient approval is not required.'
            : 'Readiness uses saved provider settings and current contact approvals.'}{' '}
        Only explicitly selected recipients receive alerts. Phone numbers are optional.
      </p>
      <ul className="flex flex-col gap-2">
        {data.recipients.map((r) => (
          <li key={r.target} className="text-sm">
            <span className="font-medium">{r.name}</span> ·{' '}
            <span className={r.eligible ? 'text-success' : 'text-danger'}>
              {r.eligible ? 'Eligible' : r.reason}
            </span>
            {r.legacy && (
              <span className="text-muted-foreground"> · Legacy standalone destination</span>
            )}
          </li>
        ))}
      </ul>
      {data.invalid_count > 0 && (
        <p role="alert" className="text-sm text-warning">
          {data.invalid_count} recipient(s) will not receive alerts. Other eligible recipients can
          still receive them.
        </p>
      )}
    </section>
  )
}
