import { t } from '../lib/i18n'
import {
  CheckCircle2,
  CircleAlert,
  CircleSlash,
  Clock,
  Eye,
  Loader2,
  ShieldOff,
} from 'lucide-react'
import type { Message } from '../lib/types'
import { useReveal } from '../lib/useReveal'
import { Concealed, RevealButton } from './Reveal'
import { OriginalMedia } from './OriginalMedia'
import { Badge } from './ui/badge'

/** The message's words. Hidden unless `revealed`; withheld messages never show anything. */
export function MessageBody({ m, revealed = false }: { m: Message; revealed?: boolean }) {
  if (m.redacted)
    return (
      <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
        <ShieldOff className="size-4" /> {t('Content withheld on purpose and never stored.')}
      </span>
    )
  const body = m.text || m.transcript
  if (!body) {
    const label =
      m.raw_type === 'revoked' || m.revoked_at
        ? 'Deleted WhatsApp message — original content is unavailable.'
        : m.type === 'poll' || m.raw_type === 'poll' || m.raw_type === 'poll_creation'
          ? 'WhatsApp poll — its question and options were not provided by OpenWA.'
          : m.type === 'other'
            ? 'Unsupported WhatsApp message — OpenWA provided no readable content.'
            : `[${t(m.type)}]`
    return <em className="text-muted-foreground">{t(label)}</em>
  }
  return (
    <span dir="auto" className="whitespace-pre-wrap break-words">
      <Concealed revealed={revealed} length={body.length}>
        {m.transcript && !m.text ? '🎤 ' : ''}
        {body}
      </Concealed>
    </span>
  )
}

/** A message with its own eye (for cards, which are not links). */
export function RevealableMessage({ m, showMedia = false }: { m: Message; showMedia?: boolean }) {
  const { revealed, toggle } = useReveal()
  const hasMedia =
    showMedia &&
    ['image', 'sticker', 'voice', 'audio', 'video', 'document'].includes(m.type) &&
    !m.redacted &&
    !m.revoked_at
  return (
    <span className="flex flex-wrap items-start gap-x-3 gap-y-2">
      <span className="min-w-0 flex-1 basis-60">
        <MessageBody m={m} revealed={revealed} />
      </span>
      {!m.redacted && (m.text || m.transcript || hasMedia) && (
        <RevealButton
          revealed={revealed}
          onToggle={toggle}
          context={`message from ${m.sender_name ?? 'unknown sender'}`}
        />
      )}
      {hasMedia && (
        <span className="basis-full">
          <OriginalMedia id={m.id} type={m.type} revealed={revealed} />
        </span>
      )}
    </span>
  )
}

const BADGE = {
  harmful: { tone: 'danger', icon: CircleAlert },
  failed: { tone: 'danger', icon: CircleAlert },
  review: { tone: 'warning', icon: Eye },
  safe: { tone: 'success', icon: CheckCircle2 },
  skipped: { tone: 'neutral', icon: CircleSlash },
  processing: { tone: 'info', icon: Loader2 },
  pending: { tone: 'neutral', icon: Clock },
} as const

/** The verdict when there is one, otherwise the processing status (failed, skipped, pending...). */
export function VerdictBadge({
  m,
}: {
  m: Pick<Message, 'verdict' | 'status' | 'failure' | 'skip_reason' | 'review_reason'>
}) {
  const label = m.verdict ?? m.status
  const b = BADGE[label as keyof typeof BADGE] ?? BADGE.pending
  return (
    <Badge tone={b.tone} title={m.failure ?? m.skip_reason ?? m.review_reason ?? undefined}>
      <b.icon /> {label}
    </Badge>
  )
}

export function Failure({ m }: { m: Pick<Message, 'failure' | 'skip_reason' | 'review_reason'> }) {
  const reason = m.failure || m.skip_reason || m.review_reason
  if (!reason) return null
  return (
    <span className={m.failure ? 'text-xs text-danger' : 'text-xs text-muted-foreground'}>
      {t(reason)}
    </span>
  )
}
