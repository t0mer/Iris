import {
  CheckCircle2,
  CircleAlert,
  CircleSlash,
  Clock,
  Eye,
  Loader2,
  ShieldOff,
} from 'lucide-react'
import { strings, t } from '../lib/i18n'
import type { Message } from '../lib/types'
import { useReveal } from '../lib/useReveal'
import { Concealed, RevealButton } from './Reveal'
import { Badge } from './ui/badge'

/** The message's words. Hidden unless `revealed`; withheld messages never show anything. */
export function MessageBody({ m, revealed = false }: { m: Message; revealed?: boolean }) {
  if (m.redacted)
    return (
      <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
        <ShieldOff className="size-4" /> {t('messageBody.withheld')}
      </span>
    )
  const body = m.text || m.transcript
  if (!body)
    return (
      <em className="text-muted-foreground">
        [{(strings.messageTypes as Record<string, string>)[m.type] ?? m.type}]
      </em>
    )
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
export function RevealableMessage({ m }: { m: Message }) {
  const { revealed, toggle } = useReveal()
  return (
    <span className="flex flex-wrap items-start gap-x-3 gap-y-2">
      <span className="min-w-0 flex-1 basis-60">
        <MessageBody m={m} revealed={revealed} />
      </span>
      {!m.redacted && (m.text || m.transcript) && (
        <RevealButton
          revealed={revealed}
          onToggle={toggle}
          context={t('messageBody.messageFrom', m.sender_name ?? t('messageBody.unknownSender'))}
        />
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
export function VerdictBadge({ m }: { m: Pick<Message, 'verdict' | 'status' | 'failure'> }) {
  const label = m.verdict ?? m.status
  const b = BADGE[label as keyof typeof BADGE] ?? BADGE.pending
  const text =
    (strings.verdicts as Record<string, string>)[label] ??
    (strings.statuses as Record<string, string>)[label] ??
    label
  return (
    <Badge tone={b.tone} title={m.failure ?? undefined}>
      <b.icon /> {text}
    </Badge>
  )
}

export function Failure({ m }: { m: Pick<Message, 'failure'> }) {
  if (!m.failure) return null
  return <span className="text-xs text-danger">{m.failure}</span>
}
