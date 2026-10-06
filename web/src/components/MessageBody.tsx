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
import { Badge } from './ui/badge'

export function MessageBody({ m }: { m: Message }) {
  if (m.redacted)
    return (
      <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
        <ShieldOff className="size-4" /> Content withheld. Only the details are kept.
      </span>
    )
  const body = m.text || m.transcript
  if (!body) return <em className="text-muted-foreground">[{m.type}]</em>
  return (
    <span dir="auto" className="whitespace-pre-wrap break-words">
      {m.transcript && !m.text ? '🎤 ' : ''}
      {body}
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
  return (
    <Badge tone={b.tone} title={m.failure ?? undefined}>
      <b.icon /> {label}
    </Badge>
  )
}

export function Failure({ m }: { m: Pick<Message, 'failure'> }) {
  if (!m.failure) return null
  return <span className="text-xs text-danger">{m.failure}</span>
}
