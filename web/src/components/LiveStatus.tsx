import { cn } from '../lib/cn'
import { t } from '../lib/i18n'
import type { LiveStatus as Status } from '../lib/live'

/** Says whether the page is updating by itself. Colour is never the only signal. */
export function LiveStatus({ status, compact = false }: { status: Status; compact?: boolean }) {
  if (status === 'unsupported') return null
  const live = status === 'live'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs text-muted-foreground',
        compact && 'ms-auto',
      )}
      title={live ? t('ui.liveHint') : t('ui.reconnectingHint')}
    >
      <span
        aria-hidden
        className={cn('size-2 rounded-full', live ? 'bg-success' : 'bg-warning animate-pulse')}
      />
      {live ? t('ui.live') : t('ui.reconnecting')}
    </span>
  )
}
