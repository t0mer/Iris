import { categoryLabel, strings, t } from '../lib/i18n'
import { he } from '../lib/he'
import { BellOff, CheckCheck, CircleAlert, Mic, ShieldOff } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '../lib/cn'
import { MessageFlags } from './MessageFlags'
import { revokedClass } from '../lib/revoked'
import { relativeTime } from '../lib/format'
import type { Alert } from '../lib/types'
import { KidStack } from './KidAvatar'
import { MediaBadge } from './MediaPlayer'
import { Concealed } from './Reveal'
import { Badge } from './ui/badge'

const DELIVERY: Record<
  string,
  { label: string; tone: 'danger' | 'warning' | 'neutral'; icon: typeof CircleAlert }
> = {
  failed: { label: he('Not delivered'), tone: 'danger', icon: CircleAlert },
  partial: { label: he('Some parents notified'), tone: 'warning', icon: CircleAlert },
  suppressed: { label: he('Held back'), tone: 'neutral', icon: BellOff },
  pending: { label: he('Sending'), tone: 'warning', icon: CircleAlert },
}

/** One alert as a row: severity bar, who, where, what was said, and what state it is in. */
export function AlertRow({ alert: a, revealed = false }: { alert: Alert; revealed?: boolean }) {
  const open = a.status === 'new'
  const delivery = DELIVERY[a.delivery_status]
  const voice = a.quote?.startsWith('🎤')
  return (
    <li>
      <Link
        to={`/alerts/${a.id}`}
        className={cn(
          'group relative flex flex-col gap-1.5 py-3.5 ps-5 pe-4 hover:bg-surface-2/60 sm:ps-6',
          revokedClass(a, 'row'),
        )}
      >
        <span
          aria-hidden
          className={cn(
            'absolute inset-y-3 start-0 w-1 rounded-e-full',
            open ? 'bg-danger' : 'bg-border-strong',
          )}
        />
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <KidStack names={a.kid_names} />
          <span className="font-medium">{strings.names.join(a.kid_names)}</span>
          {a.chat_name && (
            <span className="text-sm text-muted-foreground">{t('names.in', a.chat_name)}</span>
          )}
          <span className="ms-auto text-xs text-muted-foreground tabular">
            {relativeTime(a.created_at)}
          </span>
        </span>
        <span className="line-clamp-2 max-w-prose text-[15px]" dir="auto">
          {a.redacted ? (
            <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
              <ShieldOff className="size-4" />
              {he('Content withheld. Review the chat directly.')}
            </span>
          ) : a.quote === null ? (
            <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
              <ShieldOff className="size-4" />
              {he('Kept out of the alert. Open it to read.')}
            </span>
          ) : (
            <>
              {voice && <Mic className="me-1 inline size-4 text-muted-foreground" />}
              <Concealed revealed={revealed} length={a.quote?.length}>
                {a.quote?.replace(/^🎤\s*/, '')}
              </Concealed>
            </>
          )}
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge tone="danger">
            <CircleAlert /> {categoryLabel(a.categories[0])}{' '}
            <span className="tabular">{a.max_score.toFixed(2)}</span>
          </Badge>
          {a.categories.slice(1, 3).map((c) => (
            <Badge key={c}>{categoryLabel(c)}</Badge>
          ))}
          {!open && (
            <Badge tone="success">
              <CheckCheck /> {a.status === 'dismissed' ? he('Dismissed') : he('Seen')}
            </Badge>
          )}
          {a.media && !a.redacted && <MediaBadge media={a.media} />}
          <MessageFlags
            m={{ id: a.message_id, edited_at: a.edited_at, revoked_at: a.revoked_at }}
          />
          {delivery && (
            <Badge tone={delivery.tone} title={a.delivery_error ?? undefined}>
              <delivery.icon /> {delivery.label}
            </Badge>
          )}
        </span>
      </Link>
    </li>
  )
}
