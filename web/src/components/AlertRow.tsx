import { BellOff, CheckCheck, CircleAlert, Mic, ShieldOff } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '../lib/cn'
import { MessageFlags } from './MessageFlags'
import { revokedClass } from '../lib/revoked'
import { relativeTime } from '../lib/format'
import type { Alert } from '../lib/types'
import { KidStack } from './KidAvatar'
import { MediaBadge } from './MediaPlayer'
import { Badge } from './ui/badge'

const DELIVERY: Record<
  string,
  { label: string; tone: 'danger' | 'warning' | 'neutral'; icon: typeof CircleAlert }
> = {
  failed: { label: 'Not delivered', tone: 'danger', icon: CircleAlert },
  suppressed: { label: 'Held back', tone: 'neutral', icon: BellOff },
  pending: { label: 'Sending', tone: 'warning', icon: CircleAlert },
}

/** One alert as a row: severity bar, who, where, what was said, and what state it is in. */
export function AlertRow({ alert: a }: { alert: Alert }) {
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
          <span className="font-medium">{a.kid_names.join(' and ')}</span>
          {a.chat_name && <span className="text-sm text-muted-foreground">in {a.chat_name}</span>}
          <span className="ms-auto text-xs text-muted-foreground tabular">
            {relativeTime(a.created_at)}
          </span>
        </span>
        <span className="line-clamp-2 max-w-prose text-[15px]" dir="auto">
          {a.redacted ? (
            <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
              <ShieldOff className="size-4" /> Content withheld. Review the chat directly.
            </span>
          ) : (
            <>
              {voice && <Mic className="me-1 inline size-4 text-muted-foreground" />}
              {a.quote?.replace(/^🎤\s*/, '')}
            </>
          )}
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge tone="danger">
            <CircleAlert /> {a.categories[0]}{' '}
            <span className="tabular">{a.max_score.toFixed(2)}</span>
          </Badge>
          {a.categories.slice(1, 3).map((c) => (
            <Badge key={c}>{c}</Badge>
          ))}
          {!open && (
            <Badge tone="success">
              <CheckCheck /> {a.status === 'dismissed' ? 'Dismissed' : 'Seen'}
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
